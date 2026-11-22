//! IC:13：只有跨域 ExactCommand 的整数用规范十进制文本。AdvanceBar 的 Change
//! 与撮合模型继续用原来的数值合同；两种编码解出同一个 Change 再比较。
use super::model::{Change, Order, OrderKind, Side};
use serde::{Deserialize, Serialize};

pub(super) mod decimal {
    use serde::{Deserialize, Deserializer, Serializer};

    pub fn serialize<S: Serializer>(n: &i64, s: S) -> Result<S::Ok, S::Error> {
        s.collect_str(n)
    }

    pub fn deserialize<'de, D: Deserializer<'de>>(d: D) -> Result<i64, D::Error> {
        let text = String::deserialize(d)?;
        crate::session_protocol::parse_canonical_i64_typed(&text, "精确整数")
            .map_err(serde::de::Error::custom)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(
    remote = "OrderKind",
    tag = "kind",
    rename_all = "snake_case",
    deny_unknown_fields
)]
enum SignedKind {
    Limit {
        #[serde(with = "decimal")]
        price: i64,
    },
    Market {
        #[serde(with = "decimal")]
        exec_index: i64,
    },
}

#[derive(Serialize, Deserialize)]
#[serde(remote = "Order", deny_unknown_fields)]
struct SignedOrder {
    command_id: String,
    family_id: String,
    chong_id: String,
    #[serde(with = "decimal")]
    revision: i64,
    side: Side,
    #[serde(with = "decimal")]
    quantity: i64,
    #[serde(with = "SignedKind")]
    kind: OrderKind,
    eligibility_ref: String,
    projection_manifest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(
    remote = "Change",
    tag = "kind",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub(super) enum SignedChange {
    Submit {
        #[serde(with = "SignedOrder")]
        order: Order,
    },
    Cancel {
        family_id: String,
        command_id: String,
        eligibility_ref: String,
    },
    Replace {
        #[serde(with = "SignedOrder")]
        order: Order,
    },
}

#[derive(Serialize)]
pub(super) struct Plan<'a>(#[serde(with = "SignedChange")] pub &'a Change);
