use std::path::Path;

/// 诊断中的目录名必须可以原样交给文件系统。
pub(super) fn directory_text(path: &Path) -> Option<&str> {
    path.to_str().filter(|_| path.is_dir())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn does_not_report_regular_file() {
        let file = tempfile::NamedTempFile::new().unwrap();
        assert!(file.path().is_file());
        assert_eq!(directory_text(file.path()), None);
    }

    // 复现 Linux 文件名中的原始 0xff 字节；其它平台不运行这条字节级用例。
    #[cfg(target_os = "linux")]
    #[test]
    fn does_not_report_directory_with_invalid_utf8() {
        use std::{ffi::OsString, os::unix::ffi::OsStringExt};

        let dir = tempfile::tempdir().unwrap();
        let path = dir
            .path()
            .join(OsString::from_vec(b"external-\xff".to_vec()));
        std::fs::create_dir(&path).unwrap();
        assert!(path.is_dir());
        assert_eq!(directory_text(&path), None);
    }
}
