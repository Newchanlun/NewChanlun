//! #1419：原件索引固定分片；一次追加只重分配目标片，旧片与旧许可仍共存到成功替换。
use super::{
    capture_allocation::scratch::{NativeReservation, ScratchFailure, WorkScope},
    CodecError, NativeCountsSubsetAdmission, NativeNode, NodeDigest,
};
use std::collections::HashMap;

pub(super) const SHARDS: usize = 256;

// STARTS[i] = round(65536 · (2^(i / SHARDS) − 1))。均匀摘要下各片跨一个倍程错开。
const STARTS: [u16; SHARDS] = [
    0, 178, 356, 535, 714, 893, 1073, 1254, 1435, 1617, 1799, 1981,
    2164, 2348, 2532, 2716, 2902, 3087, 3273, 3460, 3647, 3834, 4022, 4211,
    4400, 4590, 4780, 4971, 5162, 5353, 5546, 5738, 5932, 6125, 6320, 6514,
    6710, 6906, 7102, 7299, 7496, 7694, 7893, 8092, 8292, 8492, 8693, 8894,
    9096, 9298, 9501, 9704, 9908, 10113, 10318, 10524, 10730, 10937, 11144, 11352,
    11560, 11769, 11979, 12189, 12400, 12611, 12823, 13036, 13249, 13462, 13676, 13891,
    14106, 14322, 14539, 14756, 14974, 15192, 15411, 15630, 15850, 16071, 16292, 16514,
    16737, 16960, 17183, 17408, 17633, 17858, 18084, 18311, 18538, 18766, 18995, 19224,
    19454, 19684, 19915, 20147, 20379, 20612, 20846, 21080, 21315, 21550, 21786, 22023,
    22260, 22498, 22737, 22977, 23216, 23457, 23698, 23940, 24183, 24426, 24670, 24915,
    25160, 25406, 25652, 25900, 26148, 26396, 26645, 26895, 27146, 27397, 27649, 27902,
    28155, 28409, 28664, 28919, 29175, 29432, 29690, 29948, 30207, 30466, 30727, 30988,
    31249, 31512, 31775, 32039, 32303, 32568, 32834, 33101, 33369, 33637, 33906, 34175,
    34446, 34717, 34988, 35261, 35534, 35808, 36083, 36359, 36635, 36912, 37190, 37468,
    37747, 38028, 38308, 38590, 38872, 39155, 39439, 39724, 40009, 40295, 40582, 40870,
    41158, 41448, 41738, 42029, 42320, 42613, 42906, 43200, 43495, 43790, 44087, 44384,
    44682, 44981, 45280, 45581, 45882, 46184, 46487, 46791, 47095, 47401, 47707, 48014,
    48322, 48631, 48940, 49251, 49562, 49874, 50187, 50500, 50815, 51131, 51447, 51764,
    52082, 52401, 52721, 53041, 53363, 53685, 54008, 54333, 54658, 54983, 55310, 55638,
    55966, 56296, 56626, 56957, 57289, 57622, 57956, 58291, 58627, 58964, 59301, 59640,
    59979, 60319, 60661, 61003, 61346, 61690, 62035, 62381, 62727, 63075, 63424, 63774,
    64124, 64476, 64828, 65182,
];

pub(super) struct IndexShard {
    // 表及其原件先释放，才归还这张表的许可。
    pub(super) table: HashMap<NodeDigest, NativeNode>,
    pub(super) permit: Option<NativeReservation>,
}

pub(super) struct NativeCaptureIndex {
    // 固定 256 个表头及许可槽，不在热路径栈上搬运，也不随表扩容而再分配。
    shards: Vec<IndexShard>,
    storage_permit: Option<NativeReservation>,
}
impl NativeCaptureIndex {
    pub(super) const STORAGE_BYTES: usize = SHARDS * std::mem::size_of::<IndexShard>();

    #[cfg(test)]
    pub(super) fn new() -> Self {
        Self::from_keys(std::iter::empty(), None).unwrap()
    }

    // 分片仅选容器；片内仍用标准 RandomState，未核摘要不参与弱哈希查找。
    // 固定分片使同一输入的容量阶梯不受随机种子影响；集中到一片也仍受原 cap 限制。
    pub(super) fn shard(digest: &NodeDigest) -> usize {
        let prefix = u16::from_be_bytes([digest[0], digest[1]]);
        STARTS.partition_point(|start| *start <= prefix) - 1
    }
    pub(super) fn target(&self, digest: &NodeDigest) -> &HashMap<NodeDigest, NativeNode> {
        &self.shards[Self::shard(digest)].table
    }
    pub(super) fn target_mut(
        &mut self,
        digest: &NodeDigest,
    ) -> &mut IndexShard {
        &mut self.shards[Self::shard(digest)]
    }
    pub(super) fn get(&self, digest: &NodeDigest) -> Option<&NativeNode> {
        self.target(digest).get(digest)
    }
    pub(super) fn get_mut(&mut self, digest: &NodeDigest) -> Option<&mut NativeNode> {
        self.target_mut(digest).table.get_mut(digest)
    }
    pub(super) fn insert(&mut self, digest: NodeDigest, node: NativeNode) -> Option<NativeNode> {
        self.target_mut(&digest).table.insert(digest, node)
    }
    #[cfg(test)]
    pub(super) fn remove(&mut self, digest: &NodeDigest) -> Option<NativeNode> {
        self.target_mut(digest).table.remove(digest)
    }
    pub(super) fn len(&self) -> usize {
        self.shards.iter().map(|shard| shard.table.len()).sum()
    }
    pub(super) fn capacity(&self) -> usize {
        self.shards.iter().map(|shard| shard.table.capacity()).sum()
    }
    pub(super) fn control_bytes(&self) -> usize {
        // 固定堆块另计实际布局；桶控制区继续沿用单片上界。
        self.storage_bytes().saturating_add(
            self.shards
                .iter()
                .map(|shard| shard.table.capacity())
                .filter(|&capacity| capacity != 0)
                .map(|capacity| capacity.saturating_mul(2).saturating_add(16))
                .sum(),
        )
    }
    pub(super) fn iter(&self) -> impl Iterator<Item = (&NodeDigest, &NativeNode)> {
        self.shards.iter().flat_map(|shard| shard.table.iter())
    }
    pub(super) fn values(&self) -> impl Iterator<Item = &NativeNode> {
        self.shards.iter().flat_map(|shard| shard.table.values())
    }
    pub(super) fn values_mut(&mut self) -> impl Iterator<Item = &mut NativeNode> {
        self.shards.iter_mut().flat_map(|shard| shard.table.values_mut())
    }
    pub(super) fn drain(&mut self) -> impl Iterator<Item = (NodeDigest, NativeNode)> + '_ {
        self.shards.iter_mut().flat_map(|shard| shard.table.drain())
    }
    pub(super) fn storage_bytes(&self) -> usize {
        self.shards.capacity() * std::mem::size_of::<IndexShard>()
    }
    pub(super) fn table_permits(&self) -> impl Iterator<Item = &NativeReservation> {
        self.shards.iter().filter_map(|shard| shard.permit.as_ref())
    }
    pub(super) fn permits(&self) -> impl Iterator<Item = &NativeReservation> {
        self.storage_permit.iter().chain(self.table_permits())
    }
    pub(super) fn from_keys<'a>(
        keys: impl Iterator<Item = &'a NodeDigest>,
        work: Option<&WorkScope>,
    ) -> Result<Self, CodecError> {
        let admission = NativeCountsSubsetAdmission(work);
        let mut counts = [0usize; SHARDS];
        for key in keys {
            let count = &mut counts[Self::shard(key)];
            *count = count.checked_add(1).ok_or_else(|| {
                admission.failure(ScratchFailure::Budget)
            })?;
        }
        let storage_permit = admission.reserve(Self::STORAGE_BYTES)?;
        let mut staged = Self {
            shards: Vec::new(),
            storage_permit,
        };
        staged
            .shards
            .try_reserve_exact(SHARDS)
            .map_err(|_| admission.failure(ScratchFailure::Allocation))?;
        for count in counts {
            let permit = admission.hash_room::<NodeDigest, NativeNode>(0, 0, count)?;
            staged.shards.push(IndexShard {
                table: HashMap::new(),
                permit,
            });
        }
        // 表头块已预付。全片桶许可齐备才分配首张桶表；失败时各表先于自己的许可析构。
        for (shard, count) in staged.shards.iter_mut().zip(counts) {
            shard.table.try_reserve(count).map_err(|_| {
                admission.failure(ScratchFailure::Allocation)
            })?;
        }
        Ok(staged)
    }
    #[cfg(test)]
    fn with_hasher(state: std::collections::hash_map::RandomState) -> Self {
        let mut index = Self::new();
        for shard in &mut index.shards {
            shard.table = HashMap::with_hasher(state.clone());
        }
        index
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::{hash_map::RandomState, BTreeSet};

    fn digest(i: u64) -> NodeDigest {
        super::super::frame(0, &i.to_le_bytes())
    }
    fn node() -> NativeNode {
        NativeNode::new(0, Vec::new())
    }

    /// CD g35→g36 约增长 5.7%；理想几何分片在 6% 窗口最多覆盖
    /// ceil(SHARDS · log2(1.06)) 片。用均匀前缀序列（每 65536 条遍历一次）核实际扩容，
    /// 非几何等分会在同一个窗口覆盖全部 256 片。
    #[test]
    fn shard_doublings_do_not_cluster_within_one_generation_of_growth() {
        let mut tables: [_; SHARDS] = std::array::from_fn(|_| HashMap::new());
        let mut growths = Vec::new();
        for i in 0..1_000_000u32 {
            let mut key = [0u8; 32];
            key[..2].copy_from_slice(&(i as u16).reverse_bits().to_be_bytes());
            key[2..6].copy_from_slice(&i.to_be_bytes());
            let shard = NativeCaptureIndex::shard(&key);
            let table = &mut tables[shard];
            let old_capacity = table.capacity();
            table.insert(key, ());
            if table.capacity() != old_capacity && i >= 450_000 {
                growths.push((i, shard));
            }
        }
        assert_eq!(
            growths.iter().map(|&(_, shard)| shard).collect::<BTreeSet<_>>().len(),
            SHARDS,
            "观察窗口超过一个倍程，每片至少扩容一次",
        );
        let (start, clustered) = growths
            .iter()
            .enumerate()
            .map(|(i, &(n, _))| (n, growths[i..].partition_point(|&(m, _)| m * 100 < n * 106)))
            .max_by_key(|&(_, count)| count)
            .unwrap();
        let ideal = (SHARDS as f64 * 1.06f64.log2()).ceil() as usize;
        assert!(
            clustered <= ideal + 2,
            "节点数自 {start} 起增长 6% 内有 {clustered} 次扩容；理论 {ideal}，给前缀取整两片余量"
        );
    }

    #[test]
    fn shard_i_owns_a_geometric_share_of_the_digest_space() {
        let mut width = [0usize; SHARDS];
        for prefix in 0..=u16::MAX {
            let mut low = [0u8; 32];
            low[..2].copy_from_slice(&prefix.to_be_bytes());
            let mut high = [0xffu8; 32];
            high[..2].copy_from_slice(&prefix.to_be_bytes());
            let shard = NativeCaptureIndex::shard(&low);
            assert_eq!(shard, NativeCaptureIndex::shard(&high), "分片只看前两字节");
            width[shard] += 1;
        }
        let edge = |i: usize| {
            (65536.0 * (2f64.powf(i as f64 / SHARDS as f64) - 1.0)).round() as usize
        };
        for (i, w) in width.into_iter().enumerate() {
            assert!(w > 0);
            assert_eq!(w, edge(i + 1) - edge(i), "第 {i} 片的取整区间");
        }
    }

    #[test]
    fn same_digest_lands_in_same_shard_across_hashers_orders_and_cold_reserve() {
        let keys: Vec<NodeDigest> = (0..20_000u64).map(digest).collect();
        let mut forward = NativeCaptureIndex::with_hasher(RandomState::new());
        for key in &keys {
            forward.insert(*key, node());
        }
        let mut backward = NativeCaptureIndex::with_hasher(RandomState::new());
        for key in keys.iter().rev() {
            backward.insert(*key, node());
        }
        let mut cold = NativeCaptureIndex::from_keys(keys.iter(), None).unwrap();
        for key in &keys {
            cold.insert(*key, node());
        }
        for i in 0..SHARDS {
            let members = |index: &NativeCaptureIndex| {
                index.shards[i].table.keys().copied().collect::<BTreeSet<_>>()
            };
            assert!(!members(&forward).is_empty(), "第 {i} 片应有成员");
            assert_eq!(members(&forward), members(&backward), "第 {i} 片");
            assert_eq!(members(&forward), members(&cold), "第 {i} 片");
            assert_eq!(
                forward.shards[i].table.capacity(),
                backward.shards[i].table.capacity(),
                "第 {i} 片容量阶梯不随种子与插入次序变化"
            );
        }
    }
}
