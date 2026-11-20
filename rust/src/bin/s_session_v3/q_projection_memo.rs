//! #1419：一份已夹持的 Packed 图像至多保留一个正文投影。只存完整锚和派生节点，
//! 不存应答、片段证明、事务或消费者 Job 的访问资格。
use super::*;
use newchan_rust::s_content::{
    access::Access, fragment::Fragment, NodeDigest, NodeRead, NodeSource,
};
use sc::capture_allocation::audit_json::JsonView;

#[derive(Default)]
pub(super) struct Slot {
    entry: Option<Box<Entry>>,
}

struct Entry {
    generation: i64,
    mode: projection::HistoryMode,
    anchor: Box<[u8]>,
    nodes: history::QueryNodes,
    retained: u64,
}

impl Slot {
    pub(super) fn bytes(&self) -> u64 {
        self.entry.as_ref().map_or(0, |e| e.retained)
    }

    pub(super) fn fragment(
        &mut self,
        remaining: u64,
        generation: i64,
        mode: projection::HistoryMode,
        request: &q_content::Request,
        graph: &mut history::HashReader<'_>,
        resources: &q_resources::QResources,
        job: &mut dyn Access,
        build: impl FnOnce(
            &mut history::HashReader<'_>,
            &mut dyn Access,
        ) -> Result<projection::Projection, String>,
    ) -> Result<Fragment, String> {
        if let Some(entry) = self
            .entry
            .as_ref()
            .filter(|e| e.generation == generation && e.mode == mode)
        {
            let anchor: Value = serde_json::from_slice(&entry.anchor).map_err(err)?;
            let actual = JsonView::Plain(&anchor);
            reader::check_projection_anchor_view(actual, request.anchor_view())?;
            let root = sc::TransportRef::from_json_view(bj::field(actual, "projection_ref"))
                .and_then(|r| r.try_owned_ref())
                .map_err(err)?;
            return request.read(
                &mut Nodes {
                    derived: &entry.nodes,
                    base: graph,
                },
                root.view(),
                resources,
                job,
            );
        }

        let actual = build(graph, job)?;
        reader::check_projection_anchor_view(actual.anchor_view().view(), request.anchor_view())?;
        let fragment = request.read(graph, actual.root.view(), resources, job)?;
        if remaining > 0 {
            if let Some(nodes) = graph.take_query_nodes() {
                let anchor = serde_json::to_vec(&actual.anchor_view().view())
                    .map_err(err)?
                    .into_boxed_slice();
                // NativeTree 的既有树槽保守上界包括键及 CodecVec 本体；正文按实际容量另计。
                let bytes = size_of::<Entry>()
                    .checked_add(anchor.len())
                    .and_then(|n| n.checked_add(nodes.allocation_bytes()))
                    .and_then(|n| {
                        nodes
                            .values()
                            .try_fold(n, |sum, (_, body)| sum.checked_add(body.capacity()))
                    });
                if let Some(retained) = bytes
                    .and_then(|n| u64::try_from(n).ok())
                    .filter(|n| *n <= remaining)
                {
                    self.entry = Some(Box::new(Entry {
                        generation,
                        mode,
                        anchor,
                        nodes,
                        retained,
                    }));
                }
            }
        }
        Ok(fragment)
    }
}

struct Nodes<'a> {
    derived: &'a history::QueryNodes,
    base: &'a mut dyn NodeSource,
}
impl NodeSource for Nodes<'_> {
    fn max_render_bytes(&self) -> Option<u64> {
        self.base.max_render_bytes()
    }
    fn read(&mut self, digest: &NodeDigest) -> Result<NodeRead, sc::CodecError> {
        match self.derived.get(digest) {
            Some((tag, body)) => Ok(NodeRead::Found {
                tag: *tag,
                body: body.to_vec(),
            }),
            None => self.base.read(digest),
        }
    }
}
