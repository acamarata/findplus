//! The committed tray icon PNGs are template-style and match the generator's
//! contract between the two states.
//!
//! Purpose    : Pin packaging/scripts/gen-tray-icons.py's guarantees
//!              mechanically: every committed PNG decodes to the size
//!              macOS's ~18pt menu bar expects, carries no colour
//!              information (the template-image convention -- black,
//!              alpha-only shape), and the "dim" variant traces the exact
//!              same glyph as the normal one, just at reduced alpha, never a
//!              different shape.
//! Inputs     : desktop/src-tauri/icons/tray-fplus{,-dim}.png{,@2x}, decoded
//!              through `tauri::image::Image::from_path`, the same call
//!              tray_icon.rs makes at runtime.
//! Constraints: Checks the invariants the generator promises rather than
//!              shelling out to it, so `cargo test` needs no Python
//!              interpreter and no network access.

const SIZE_1X: u32 = 22;
const SIZE_2X: u32 = 44;

fn icon_path(name: &str) -> std::path::PathBuf {
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("icons")
        .join(name)
}

fn decode(name: &str) -> tauri::image::Image<'static> {
    tauri::image::Image::from_path(icon_path(name))
        .unwrap_or_else(|e| panic!("{name} failed to decode as PNG: {e}"))
}

fn max_alpha(img: &tauri::image::Image<'static>) -> u8 {
    img.rgba().as_chunks::<4>().0.iter().map(|px| px[3]).max().unwrap()
}

#[test]
fn normal_and_dim_icons_are_22x22_and_44x44() {
    for name in ["tray-fplus.png", "tray-fplus-dim.png"] {
        let img = decode(name);
        assert_eq!((img.width(), img.height()), (SIZE_1X, SIZE_1X), "{name}");
    }
    for name in ["tray-fplus@2x.png", "tray-fplus-dim@2x.png"] {
        let img = decode(name);
        assert_eq!((img.width(), img.height()), (SIZE_2X, SIZE_2X), "{name}");
    }
}

#[test]
fn every_committed_icon_is_alpha_only_black() {
    for name in [
        "tray-fplus.png",
        "tray-fplus@2x.png",
        "tray-fplus-dim.png",
        "tray-fplus-dim@2x.png",
    ] {
        let img = decode(name);
        for px in img.rgba().as_chunks::<4>().0.iter() {
            assert_eq!(
                &px[0..3],
                &[0, 0, 0],
                "{name}: template PNGs carry no colour, only alpha"
            );
        }
    }
}

#[test]
fn normal_icon_reaches_full_opacity_over_a_transparent_background() {
    let img = decode("tray-fplus.png");
    let rgba = img.rgba();
    assert!(
        rgba.as_chunks::<4>().0.iter().any(|px| px[3] == 255),
        "the glyph must be fully opaque somewhere, not a washed-out icon"
    );
    assert!(
        rgba.as_chunks::<4>().0.iter().any(|px| px[3] == 0),
        "the background must be fully transparent, not a solid square"
    );
}

#[test]
fn dim_icon_sits_in_the_35_to_40_percent_alpha_band() {
    let peak = max_alpha(&decode("tray-fplus-dim.png"));
    let pct = f64::from(peak) / 255.0 * 100.0;
    assert!(
        (35.0..=40.0).contains(&pct),
        "dim icon peak alpha {peak} is {pct:.1}% of 255, outside the \
         35-40% band the owner asked for"
    );
}

#[test]
fn dim_icon_traces_the_same_glyph_as_the_normal_one_only_dimmer() {
    let normal = decode("tray-fplus.png");
    let dim = decode("tray-fplus-dim.png");
    let dim_peak = max_alpha(&dim);
    for (n, d) in normal
        .rgba()
        .as_chunks::<4>().0.iter()
        .zip(dim.rgba().as_chunks::<4>().0.iter())
    {
        assert_eq!(
            n[3] > 0,
            d[3] > 0,
            "dim icon must trace the exact same glyph shape as the normal one"
        );
        if n[3] > 0 {
            assert_eq!(d[3], dim_peak, "every glyph pixel dims by the same amount");
        }
    }
}

#[test]
fn the_2x_variant_is_an_exact_nearest_neighbour_upscale_of_1x() {
    for (base, retina) in [
        ("tray-fplus.png", "tray-fplus@2x.png"),
        ("tray-fplus-dim.png", "tray-fplus-dim@2x.png"),
    ] {
        assert_scales_2x(base, retina);
    }
}

fn assert_scales_2x(base: &str, retina: &str) {
    let a = decode(base);
    let b = decode(retina);
    assert_eq!(b.width(), a.width() * 2, "{retina} width");
    assert_eq!(b.height(), a.height() * 2, "{retina} height");
    let (aw, ah) = (a.width() as usize, a.height() as usize);
    let (a_rgba, b_rgba) = (a.rgba(), b.rgba());
    for y in 0..ah {
        for x in 0..aw {
            let src = &a_rgba[(y * aw + x) * 4..(y * aw + x) * 4 + 4];
            for (dy, dx) in [(0, 0), (0, 1), (1, 0), (1, 1)] {
                let (by, bx) = (y * 2 + dy, x * 2 + dx);
                let idx = (by * (aw * 2) + bx) * 4;
                assert_eq!(
                    &b_rgba[idx..idx + 4],
                    src,
                    "{retina} pixel ({bx},{by}) must match {base} pixel ({x},{y})"
                );
            }
        }
    }
}

#[test]
fn the_glyph_is_neither_empty_nor_a_solid_square() {
    let img = decode("tray-fplus.png");
    let total = (img.width() * img.height()) as usize;
    let opaque = img.rgba().as_chunks::<4>().0.iter().filter(|px| px[3] >= 128).count();
    assert!(
        opaque > 0 && opaque < total,
        "a blank or fully solid icon is not a glyph (opaque={opaque}/{total})"
    );
}
