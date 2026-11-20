//! #1419：原件索引固定分片；一次追加只重分配目标片，旧片与旧许可仍共存到成功替换。
use super::{
    capture_allocation::scratch::{NativeReservation, WorkScope},
    CodecError, NativeCountsSubsetAdmission, NativeNode, NodeDigest,
};
use std::collections::HashMap;

pub(super) const SHARDS: usize = 16;

pub(super) struct NativeCaptureIndex {
    shards: [HashMap<NodeDigest, NativeNode>; SHARDS],
}
impl NativeCaptureIndex {
    pub(super) fn new() -> Self {
        Self {
            shards: std::array::from_fn(|_| HashMap::new()),
        }
    }
    // 分片仅选容器；片内仍用标准 RandomState，未核摘要不参与弱哈希查找。
    // 固定分片使同一输入的容量阶梯不受随机种子影响；集中到一片也仍受原 cap 限制。
    // 第 i 片取摘要前两字节空间的 2^(i/16) 比例区间：均匀摘要下各片负载错开一个倍程，
    // 翻倍时点摊开。等分时十六片在同一两代一起扩容，单请求额度被一次耗尽（#1855 d2）。
    pub(super) fn shard(digest: &NodeDigest) -> usize {
        // STARTS[i] = round(65536 · (2^(i/16) − 1))
        const STARTS: [u16; SHARDS] = [
            0, 2902, 5932, 9096, 12400, 15850, 19454, 23216, 27146, 31249, 35534, 40009, 44682,
            49562, 54658, 59979,
        ];
        let prefix = u16::from_be_bytes([digest[0], digest[1]]);
        STARTS.partition_point(|start| *start <= prefix) - 1
    }
    pub(super) fn target(&self, digest: &NodeDigest) -> &HashMap<NodeDigest, NativeNode> {
        &self.shards[Self::shard(digest)]
    }
    pub(super) fn target_mut(
        &mut self,
        digest: &NodeDigest,
    ) -> &mut HashMap<NodeDigest, NativeNode> {
        &mut self.shards[Self::shard(digest)]
    }
    pub(super) fn get(&self, digest: &NodeDigest) -> Option<&NativeNode> {
        self.target(digest).get(digest)
    }
    pub(super) fn get_mut(&mut self, digest: &NodeDigest) -> Option<&mut NativeNode> {
        self.target_mut(digest).get_mut(digest)
    }
    pub(super) fn insert(&mut self, digest: NodeDigest, node: NativeNode) -> Option<NativeNode> {
        self.target_mut(&digest).insert(digest, node)
    }
    #[cfg(test)]
    pub(super) fn remove(&mut self, digest: &NodeDigest) -> Option<NativeNode> {
        self.target_mut(digest).remove(digest)
    }
    pub(super) fn len(&self) -> usize {
        self.shards.iter().map(HashMap::len).sum()
    }
    pub(super) fn capacity(&self) -> usize {
        self.shards.iter().map(HashMap::capacity).sum()
    }
    pub(super) fn control_bytes(&self) -> usize {
        self.shards
            .iter()
            .filter(|s| s.capacity() != 0)
            .map(|s| s.capacity().saturating_mul(2).saturating_add(16))
            .sum()
    }
    pub(super) fn iter(&self) -> impl Iterator<Item = (&NodeDigest, &NativeNode)> {
        self.shards.iter().flat_map(HashMap::iter)
    }
    pub(super) fn values(&self) -> impl Iterator<Item = &NativeNode> {
        self.shards.iter().flat_map(HashMap::values)
    }
    pub(super) fn values_mut(&mut self) -> impl Iterator<Item = &mut NativeNode> {
        self.shards.iter_mut().flat_map(HashMap::values_mut)
    }
    pub(super) fn drain(&mut self) -> impl Iterator<Item = (NodeDigest, NativeNode)> + '_ {
        self.shards.iter_mut().flat_map(HashMap::drain)
    }
    pub(super) fn reserve_keys<'a>(
        &mut self,
        keys: impl Iterator<Item = &'a NodeDigest>,
        work: Option<&WorkScope>,
    ) -> Result<[Option<NativeReservation>; SHARDS], CodecError> {
        let admission = NativeCountsSubsetAdmission(work);
        let mut counts = [0usize; SHARDS];
        for key in keys {
            let count = &mut counts[Self::shard(key)];
            *count = count.checked_add(1).ok_or_else(|| {
                admission.failure(super::capture_allocation::scratch::ScratchFailure::Budget)
            })?;
        }
        let mut permits = std::array::from_fn(|_| None);
        for (i, count) in counts.iter().copied().enumerate() {
            if count == 0 {
                continue;
            }
            permits[i] = admission.hash_room::<NodeDigest, NativeNode>(0, 0, count)?;
        }
        // 先取得全部许可，再建临时表。失败时 staged 后声明、先析构，
        // 不会把仍存活的前几片分配从父账提前释放。
        let mut staged = Self::new();
        for (i, count) in counts.into_iter().enumerate() {
            staged.shards[i].try_reserve(count).map_err(|_| {
                admission.failure(super::capture_allocation::scratch::ScratchFailure::Allocation)
            })?;
        }
        *self = staged;
        Ok(permits)
    }
    #[cfg(test)]
    pub(super) fn with_hasher(state: std::collections::hash_map::RandomState) -> Self {
        Self {
            shards: std::array::from_fn(|_| HashMap::with_hasher(state.clone())),
        }
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

    /// CD g35→g36 节点增长约 5.7%。等分时这一步会让十一片同时翻倍、共申请 1.42 亿字节。
    #[test]
    fn shard_doublings_do_not_cluster_within_one_generation_of_growth() {
        let mut index = NativeCaptureIndex::new();
        let mut growths = Vec::new();
        for i in 0..130_000u64 {
            let (len, capacity) = (index.len(), index.capacity());
            index.insert(digest(i), node());
            if index.capacity() != capacity {
                growths.push(len);
            }
        }
        let late: Vec<usize> = growths
            .into_iter()
            .filter(|&n| n >= SHARDS * 1792)
            .collect();
        assert!(
            late.len() >= SHARDS,
            "满一个倍程后每片都应至少扩容一次：{late:?}"
        );
        let (start, clustered) = late
            .iter()
            .enumerate()
            .map(|(i, &n)| (n, late[i..].partition_point(|&m| m * 100 < n * 106)))
            .max_by_key(|&(_, count)| count)
            .unwrap();
        assert!(
            clustered <= 4,
            "节点数自 {start} 起增长 6% 内有 {clustered} 片扩容；各片翻倍时点应错开"
        );
    }

    #[test]
    fn shard_i_owns_a_two_to_the_i_over_16_share_of_the_digest_space() {
        let mut width = [0u32; SHARDS];
        for prefix in 0..=u16::MAX {
            let mut low = [0u8; 32];
            low[..2].copy_from_slice(&prefix.to_be_bytes());
            let mut high = [0xffu8; 32];
            high[..2].copy_from_slice(&prefix.to_be_bytes());
            let shard = NativeCaptureIndex::shard(&low);
            assert_eq!(shard, NativeCaptureIndex::shard(&high), "分片只看前两字节");
            width[shard] += 1;
        }
        let edge = |i: usize| 65536.0 * (2f64.powf(i as f64 / SHARDS as f64) - 1.0);
        for (i, w) in width.into_iter().enumerate() {
            let expected = edge(i + 1) - edge(i);
            assert!(
                (f64::from(w) - expected).abs() <= 1.0,
                "第 {i} 片宽 {w}，应为 {expected:.1}"
            );
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
        let mut cold = NativeCaptureIndex::new();
        cold.reserve_keys(keys.iter(), None).unwrap();
        for key in &keys {
            cold.insert(*key, node());
        }
        for i in 0..SHARDS {
            let members = |index: &NativeCaptureIndex| {
                index.shards[i].keys().copied().collect::<BTreeSet<_>>()
            };
            assert!(!members(&forward).is_empty(), "第 {i} 片应有成员");
            assert_eq!(members(&forward), members(&backward), "第 {i} 片");
            assert_eq!(members(&forward), members(&cold), "第 {i} 片");
            assert_eq!(
                forward.shards[i].capacity(),
                backward.shards[i].capacity(),
                "第 {i} 片容量阶梯不随种子与插入次序变化"
            );
        }
    }
}
