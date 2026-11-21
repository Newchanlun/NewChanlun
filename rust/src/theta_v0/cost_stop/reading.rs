use super::registry::{OriginalKind, Store, Verified};
use super::{CostComponent, CostGap, CostTerm, Domain, RatePpb, RecordIdentity, SourceBinding};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum Basis {
    Measured,
    ProxyLowerBound,
}

struct CostReading {
    component: CostComponent,
    basis: Basis,
    domain: Domain,
    level: u32,
    rate: RatePpb,
}

#[cfg(not(test))]
fn parse(_: &Verified) -> Option<CostReading> {
    // TB-08 尚未裁生产读数格式；没有只靠 amount + 标签的生产口。
    None
}

#[cfg(test)]
fn parse(original: &Verified) -> Option<CostReading> {
    use super::policy::{json, object, read_domain, string, unsigned};
    let root = json(original).ok()?;
    object(
        &root,
        "<cost-reading>",
        &["schema", "component", "basis", "domain", "level", "rate"],
    )
    .ok()?;
    if string(&root, "schema").ok()? != "test-only/cost-reading/0" {
        return None;
    }
    let component = match string(&root, "component").ok()? {
        "slippage" => CostComponent::Slippage,
        "latency_error" => CostComponent::LatencyError,
        "holding" => CostComponent::Holding,
        _ => return None,
    };
    let basis = match string(&root, "basis").ok()? {
        "Measured" => Basis::Measured,
        "ProxyLowerBound" => Basis::ProxyLowerBound,
        _ => return None,
    };
    Some(CostReading {
        component,
        basis,
        domain: read_domain(&root).ok()?,
        level: unsigned(&root, "level").ok()?,
        rate: RatePpb(unsigned(&root, "rate").ok()?),
    })
}

pub(super) fn cost(
    store: Store,
    term: &CostTerm,
    domain: &Domain,
    level: u32,
    component: CostComponent,
    consumed: &mut Vec<RecordIdentity>,
) -> Result<(RatePpb, Basis), CostGap> {
    let (binding, basis) = match term {
        CostTerm::Known(source) => (source, Basis::Measured),
        CostTerm::ProxyLowerBound(source) => (source, Basis::ProxyLowerBound),
        CostTerm::Missing => return Err(CostGap::SignedMissing),
    };
    resolve(store, binding, (component, basis), domain, level, consumed).map(|rate| (rate, basis))
}

pub(super) fn holding(
    store: Store,
    binding: &SourceBinding,
    domain: &Domain,
    level: u32,
    consumed: &mut Vec<RecordIdentity>,
) -> Result<RatePpb, CostGap> {
    resolve(
        store,
        binding,
        (CostComponent::Holding, Basis::Measured),
        domain,
        level,
        consumed,
    )
}

fn resolve(
    store: Store,
    binding: &SourceBinding,
    (component, basis): (CostComponent, Basis),
    domain: &Domain,
    level: u32,
    consumed: &mut Vec<RecordIdentity>,
) -> Result<RatePpb, CostGap> {
    let SourceBinding::Bound(reference) = binding else {
        return Err(CostGap::Unbound);
    };
    let original = store
        .fetch_bound(OriginalKind::CostReading, reference)
        .map_err(|_| CostGap::OriginalUnavailable)?;
    original.trace(consumed);
    if !original.approved() {
        return Err(CostGap::OriginalUnavailable);
    }
    let reading = parse(&original).ok_or(CostGap::ReadingUnreadable)?;
    if reading.component != component
        || reading.basis != basis
        || &reading.domain != domain
        || reading.level != level
    {
        return Err(CostGap::ReadingMismatch);
    }
    Ok(reading.rate)
}
