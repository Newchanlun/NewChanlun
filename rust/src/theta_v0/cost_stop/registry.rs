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

// 登记摘要以字节保存；编译期转回身份校验使用的小写十六进制。
const fn encode_sha256(bytes: [u8; 32]) -> [u8; 64] {
    let digits = b"0123456789abcdef";
    let mut hex = [0; 64];
    let mut i = 0;
    while i < bytes.len() {
        hex[2 * i] = digits[(bytes[i] >> 4) as usize];
        hex[2 * i + 1] = digits[(bytes[i] & 0xf) as usize];
        i += 1;
    }
    hex
}

const fn hex_str(hex: &[u8; 64]) -> &str {
    match std::str::from_utf8(hex) {
        Ok(hex) => hex,
        Err(_) => panic!("登记摘要不是 UTF-8"),
    }
}

static REGISTERED: &[Row] = &[
    Row {
        kind: OriginalKind::Policy,
        key: "#1354/cost-stop-policy/P0@1",
        path: "rust/src/theta_v0/policy_records/cost-stop/P0.v1.json",
        bytes: include_bytes!("../policy_records/cost-stop/P0.v1.json"),
        sha256: {
            const HEX: [u8; 64] = encode_sha256([
                0xc2, 0xdd, 0x8b, 0x50, 0x8f, 0x65, 0x7b, 0x4b, 0xa8, 0x0b, 0x90, 0x2e, 0x1c, 0x0c,
                0xd8, 0xf1, 0xe3, 0xe3, 0x8f, 0xdc, 0xa4, 0xba, 0x33, 0xae, 0xe8, 0x9e, 0xf9, 0x7d,
                0x6d, 0x5d, 0x4a, 0x72,
            ]);
            hex_str(&HEX)
        },
        authority: APPROVAL_1559,
    },
    Row {
        kind: OriginalKind::Policy,
        key: "#1354/cost-stop-policy/P1-hl-testnet@1",
        path: "rust/src/theta_v0/policy_records/cost-stop/P1-hl-testnet.v1.json",
        bytes: include_bytes!("../policy_records/cost-stop/P1-hl-testnet.v1.json"),
        sha256: {
            const HEX: [u8; 64] = encode_sha256([
                0xbd, 0xef, 0x9c, 0x95, 0xa3, 0x3a, 0x68, 0x65, 0x2e, 0x32, 0xf8, 0xed, 0x18, 0x80,
                0x5c, 0xf2, 0x22, 0x23, 0xf8, 0x81, 0xfa, 0x29, 0x6c, 0x6c, 0xde, 0x20, 0xbe, 0xe4,
                0x7f, 0x9f, 0x08, 0x56,
            ]);
            hex_str(&HEX)
        },
        authority: APPROVAL_1559,
    },
    Row {
        kind: OriginalKind::EvidenceGate,
        key: "#1677/evidence-gate/v1",
        path: "rust/src/theta_v0/policy_records/evidence-gate.json",
        bytes: ACTIVE_EVIDENCE_GATE_JSON.as_bytes(),
        sha256: {
            const HEX: [u8; 64] = encode_sha256([
                0xca, 0x0f, 0x2e, 0xcb, 0x9c, 0x82, 0xdf, 0x6e, 0xf2, 0xf9, 0x3c, 0xfe, 0x00, 0xbc,
                0x64, 0x67, 0x43, 0xf3, 0xfd, 0x87, 0xcf, 0xa2, 0x04, 0x14, 0x43, 0x2d, 0xcd, 0x4c,
                0x3e, 0x27, 0xd2, 0xf7,
            ]);
            hex_str(&HEX)
        },
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
