use std::path::Path;

/// 只报告能原样放在一行、并可直接交给文件系统的目录名。
pub(super) fn directory_text(path: &Path) -> Option<&str> {
    path.to_str().filter(|text| {
        !text
            .chars()
            .any(|c| c.is_control() || matches!(c, '\u{2028}' | '\u{2029}'))
            && path.is_dir()
    })
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

    macro_rules! rejects_directory_containing {
        ($($name:ident => $character:literal),+ $(,)?) => {$(
            #[test]
            fn $name() {
                let dir = tempfile::tempdir().unwrap();
                let path = dir.path().join(concat!("first", $character, "second"));
                std::fs::create_dir(&path).unwrap();
                assert!(path.is_dir());
                assert_eq!(directory_text(&path), None);
            }
        )+};
    }

    rejects_directory_containing!(
        rejects_line_feed => "\n",
        rejects_carriage_return => "\r",
        rejects_tab => "\t",
        rejects_c0_control => "\x01",
        rejects_delete_control => "\x7f",
        rejects_c1_control => "\u{0085}",
        rejects_line_separator => "\u{2028}",
        rejects_paragraph_separator => "\u{2029}",
    );
}
