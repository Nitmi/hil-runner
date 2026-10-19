fn main() {
    println!("cargo:rerun-if-changed=memory.x");
    println!("cargo:rerun-if-env-changed=HIL_DK_BUILD_ID");
    println!("cargo:rerun-if-env-changed=HIL_DK_VARIANT");
    println!("cargo:rustc-link-search={}", env!("CARGO_MANIFEST_DIR"));
    let build = std::env::var("HIL_DK_BUILD_ID").expect("build through build.py");
    let variant = std::env::var("HIL_DK_VARIANT").expect("build through build.py");
    assert!(build.len() == 64 && build.bytes().all(|b| b.is_ascii_hexdigit()));
    assert!(variant == "A" || variant == "B");
    println!("cargo:rustc-env=HIL_DK_BUILD_ID={build}");
    println!("cargo:rustc-env=HIL_DK_VARIANT={variant}");
}
