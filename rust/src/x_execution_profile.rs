//! ADR 0039（#2134）：X 凭据注入的共享入口校验。
use serde_json::Value;

pub const REVISION_V1: &str = "x-execution-profile/1";
const REVISION_V2: &str = "x-execution-profile/2";
const CREDENTIAL_PREFIX: &str = "NC_X_VENUE_CREDENTIAL";

pub struct CredentialInjection<'a> {
    pub env: &'a str,
    pub file: Option<&'a str>,
}

fn valid_credential_env(name: &str) -> bool {
    if name.len() > 64 {
        return false;
    }
    match name.strip_prefix(CREDENTIAL_PREFIX).map(str::as_bytes) {
        Some([]) => true,
        Some([b'_', first, rest @ ..]) => {
            first.is_ascii_alphanumeric()
                && rest.iter().all(|c| c.is_ascii_alphanumeric() || *c == b'_')
        }
        _ => false,
    }
}

pub fn credential_injection(profile: &Value) -> Result<CredentialInjection<'_>, String> {
    let (revision, section, field) = match profile["profile_revision"].as_str() {
        Some(revision @ REVISION_V1) => (revision, "credential_scope", "credential_scope.env"),
        Some(revision @ REVISION_V2) => (revision, "credential_source", "credential_source.env"),
        _ => {
            return Err(format!(
                "VersionUnsupported：执行 profile 版本必须是 {REVISION_V1}"
            ))
        }
    };
    let env = profile[section]["env"]
        .as_str()
        .filter(|name| valid_credential_env(name))
        .ok_or_else(|| format!(
            "InvalidDomain：{field} 必须是 {CREDENTIAL_PREFIX} 或加下划线及后缀（以 ASCII 字母或数字起首，只含 ASCII 字母、数字或下划线；区分大小写；全名最多 64 字节）"
        ))?;
    // #2113 只落实 /2 的字段规则；激活 /2 及其发送合同归 ADR 0062 的实施票。
    if revision == REVISION_V2 {
        return Err(format!("VersionUnsupported：尚未启用 {REVISION_V2}"));
    }
    Ok(CredentialInjection {
        env,
        file: profile[section]["file"].as_str(),
    })
}
