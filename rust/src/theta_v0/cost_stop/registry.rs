use sha2::{Digest, Sha256};

use super::OriginalRef;
use crate::theta_v0::policy_records::ACTIVE_EVIDENCE_GATE_JSON;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum OriginalKind {
    Policy,
    EvidenceGate,
    PreregWindows,
    AmplitudeRun,
    CostReading,
}

#[derive(Clone, Copy)]
pub(super) enum Authority {
    Registered {
        reference: &'static str,
    },
    #[allow(dead_code, reason = "目前没有等待授权的登记行")]
    AwaitingApproval,
    #[cfg(test)]
    TestOnly,
}

#[derive(Clone, Copy)]
pub(super) struct Row {
    pub kind: OriginalKind,
    pub key: &'static str,
    pub path: &'static str,
    pub bytes: &'static [u8],
    pub sha256: &'static str,
    pub authority: Authority,
}

const APPROVAL_1559: Authority = Authority::Registered {
    reference: "https://github.com/xy7365527-lang/NewChanlun/issues/1559#issuecomment-6310844461",
};

static REGISTERED: &[Row] = &[
    Row {
        kind: OriginalKind::Policy,
        key: "#1354/cost-stop-policy/P0@1",
        path: "rust/src/theta_v0/policy_records/cost-stop/P0.v1.json",
        bytes: include_bytes!("../policy_records/cost-stop/P0.v1.json"),
        sha256: "c2dd8b508f657b4ba80b902e1c0cd8f1e3e38fdca4ba33aee89ef97d6d5d4a72",
        authority: APPROVAL_1559,
    },
    Row {
        kind: OriginalKind::Policy,
        key: "#1354/cost-stop-policy/P1-hl-testnet@1",
        path: "rust/src/theta_v0/policy_records/cost-stop/P1-hl-testnet.v1.json",
        bytes: include_bytes!("../policy_records/cost-stop/P1-hl-testnet.v1.json"),
        sha256: "bdef9c95a33a68652e32f8ed18805cf22223f881fa296c6cde20bee47f9f0856",
        authority: APPROVAL_1559,
    },
    Row {
        kind: OriginalKind::EvidenceGate,
        key: "#1677/evidence-gate/v1",
        path: "rust/src/theta_v0/policy_records/evidence-gate.json",
        bytes: ACTIVE_EVIDENCE_GATE_JSON.as_bytes(),
        sha256: "ca0f2ecb9c82df6ef2f93cfe00bc646743f3fd87cfa20414432dcd4c3e27d2f7",
        authority: Authority::Registered {
            reference: "docs/adr/0022-acceptance-criterion-parameters.md#修订",
        },
    },
];

#[derive(Debug, PartialEq, Eq)]
pub struct RecordIdentity {
    kind: OriginalKind,
    key: &'static str,
    path: &'static str,
    sha256: &'static str,
    reference: Option<&'static str>,
}

impl RecordIdentity {
    pub fn key(&self) -> &str {
        self.key
    }
    pub fn path(&self) -> &str {
        self.path
    }
    pub fn sha256(&self) -> &str {
        self.sha256
    }
    pub fn reference(&self) -> Option<&str> {
        self.reference
    }

    pub(super) fn copy_identity(&self) -> Self {
        Self {
            kind: self.kind,
            key: self.key,
            path: self.path,
            sha256: self.sha256,
            reference: self.reference,
        }
    }
}

pub(super) struct Verified {
    bytes: &'static [u8],
    identity: RecordIdentity,
    authority: Authority,
}

impl Verified {
    pub fn bytes(&self) -> &[u8] {
        self.bytes
    }
    pub fn identity(&self) -> &RecordIdentity {
        &self.identity
    }
    pub fn authority(&self) -> Authority {
        self.authority
    }
    pub fn approved(&self) -> bool {
        !matches!(self.authority, Authority::AwaitingApproval)
    }

    pub fn trace(&self, consumed: &mut Vec<RecordIdentity>) {
        if !consumed.contains(&self.identity) {
            consumed.push(self.identity.copy_identity());
        }
    }
}

#[derive(Debug, PartialEq, Eq)]
pub(super) enum FetchError {
    NotFound,
    WrongKind,
    DuplicateKey,
    Digest,
}

#[derive(Clone, Copy)]
enum Origin {
    Registered,
    #[cfg(test)]
    TestOnly,
}

#[derive(Clone, Copy)]
pub(super) struct Store {
    rows: &'static [Row],
    origin: Origin,
}

impl Store {
    pub fn registered() -> Self {
        Self {
            rows: REGISTERED,
            origin: Origin::Registered,
        }
    }

    #[cfg(test)]
    pub fn test_only(rows: Vec<Row>) -> Self {
        Self {
            rows: Box::leak(rows.into_boxed_slice()),
            origin: Origin::TestOnly,
        }
    }

    pub fn is_registered(self) -> bool {
        matches!(self.origin, Origin::Registered)
    }

    pub(super) fn rows_of(self, kind: OriginalKind) -> impl Iterator<Item = &'static Row> {
        self.rows.iter().filter(move |row| row.kind == kind)
    }

    pub fn fetch(self, kind: OriginalKind, key: &str) -> Result<Verified, FetchError> {
        let mut matches = self.rows.iter().filter(|row| row.key == key);
        let row = matches.next().ok_or(FetchError::NotFound)?;
        if matches.next().is_some() {
            return Err(FetchError::DuplicateKey);
        }
        if row.kind != kind {
            return Err(FetchError::WrongKind);
        }
        if sha256(row.bytes) != row.sha256 {
            return Err(FetchError::Digest);
        }
        let reference = match row.authority {
            Authority::Registered { reference } => Some(reference),
            _ => None,
        };
        Ok(Verified {
            bytes: row.bytes,
            authority: row.authority,
            identity: RecordIdentity {
                kind: row.kind,
                key: row.key,
                path: row.path,
                sha256: row.sha256,
                reference,
            },
        })
    }

    pub fn fetch_bound(
        self,
        kind: OriginalKind,
        reference: &OriginalRef,
    ) -> Result<Verified, FetchError> {
        let verified = self.fetch(kind, reference.key())?;
        if verified.identity.sha256 != reference.sha256() {
            return Err(FetchError::Digest);
        }
        Ok(verified)
    }
}

pub(super) fn sha256(bytes: &[u8]) -> String {
    format!("{:x}", Sha256::digest(bytes))
}
