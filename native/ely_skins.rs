//! Ely.by public profiles and texture transport. No credentials are sent here.
use super::{NameOrId, ResolvedProfile};
use std::{io::Read, path::PathBuf, time::Duration};

pub const SUPPORT_MARKER: &str = "HORIZON_ELY_NATIVE_V1";
pub const TEXTURE_URIS: &[&str] = &[
    "https://textures.minecraft.net/texture/{textureId}",
    "http://textures.minecraft.net/texture/{textureId}",
    "https://ely.by/storage/skins/",
    "http://ely.by/storage/skins/",
    "https://ely.by/storage/capes/",
    "http://ely.by/storage/capes/",
    "https://skinsystem.ely.by/skins/",
    "http://skinsystem.ely.by/skins/",
    "https://skinsystem.ely.by/cloaks/",
    "http://skinsystem.ely.by/cloaks/",
    "https://textures.ely.by/",
    "http://textures.ely.by/",
];

pub fn active() -> bool {
    crate::auth::current().is_some_and(|s| s.ely)
}

pub fn is_ely_texture(url: &str) -> bool {
    TEXTURE_URIS[2..].iter().any(|prefix| url.starts_with(*prefix))
}

fn fetch(url: &str, limit: u64) -> Option<Vec<u8>> {
    if !url.starts_with("https://") {
        return None;
    }
    let response = ureq::AgentBuilder::new()
        .timeout(Duration::from_secs(10))
        .redirects(0)
        .user_agent("Horizon-Ely-Integration/0.1")
        .build()
        .get(url)
        .call()
        .ok()?;
    if response.status() != 200 {
        return None;
    }
    let mut bytes = Vec::new();
    response.into_reader().take(limit + 1).read_to_end(&mut bytes).ok()?;
    (bytes.len() as u64 <= limit).then_some(bytes)
}

pub fn texture(url: &str) -> Option<Vec<u8>> {
    if !is_ely_texture(url) {
        return None;
    }
    let secure = url.replacen("http://", "https://", 1);
    fetch(&secure, 2 << 20)
}

fn valid_name(name: &str) -> bool {
    (3..=16).contains(&name.len())
        && name.bytes().all(|c| c.is_ascii_alphanumeric() || c == b'_')
}

fn profile(bytes: &[u8], key: &NameOrId) -> Option<ResolvedProfile> {
    let v: serde_json::Value = serde_json::from_slice(bytes).ok()?;
    let id = crate::auth::parse_uuid(v.get("id")?.as_str()?)?;
    let name = v.get("name")?.as_str()?.to_owned();
    if !valid_name(&name) {
        return None;
    }
    match key {
        NameOrId::Id(expected) if *expected != id => return None,
        NameOrId::Name(expected) if !expected.eq_ignore_ascii_case(&name) => return None,
        _ => {}
    }
    let properties = v.get("properties")?.as_array()?.iter().map(|p| {
        Some((
            p.get("name")?.as_str()?.to_owned(),
            p.get("value")?.as_str()?.to_owned(),
            p.get("signature").and_then(|s| s.as_str()).map(str::to_owned),
        ))
    }).collect::<Option<Vec<_>>>()?;
    Some(ResolvedProfile { id, name, properties })
}

pub fn resolve(key: &NameOrId) -> Option<ResolvedProfile> {
    let (url, cache_key) = match key {
        NameOrId::Id(id) => (
            format!("https://authserver.ely.by/session/profile/{id:032x}?unsigned=false"),
            format!("id-{id:032x}"),
        ),
        NameOrId::Name(name) if valid_name(name) => (
            format!("https://skinsystem.ely.by/profile/{name}?unsigned=false"),
            format!("name-{}", name.to_ascii_lowercase()),
        ),
        _ => return None,
    };
    // Public profile cache; never an OAuth token or a session file.
    let cache: PathBuf = std::env::current_dir().ok()?
        .join(".horizon-elyby/profiles").join(format!("{cache_key}.json"));
    if let Some(bytes) = fetch(&url, 1 << 20) {
        if let Some(result) = profile(&bytes, key) {
            if let Some(parent) = cache.parent() {
                let _ = std::fs::create_dir_all(parent);
                let _ = std::fs::write(&cache, &bytes);
            }
            return Some(result);
        }
    }
    if std::fs::metadata(&cache).ok()?.len() > 1 << 20 {
        return None;
    }
    profile(&std::fs::read(cache).ok()?, key)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn texture_origins_are_exact() {
        assert!(is_ely_texture("http://ely.by/storage/skins/a.png"));
        assert!(!is_ely_texture("https://ely.by.evil.test/storage/skins/a.png"));
        assert!(!is_ely_texture("https://ely.by@evil.test/storage/skins/a.png"));
        assert!(!is_ely_texture("http://127.0.0.1/private"));
    }

    #[test]
    fn profile_must_match_requested_identity() {
        let body = br#"{"id":"00000000000000000000000000000001","name":"Player_1","properties":[]}"#;
        assert!(profile(body, &NameOrId::Id(1)).is_some());
        assert!(profile(body, &NameOrId::Id(2)).is_none());
        assert!(profile(body, &NameOrId::Name("Other".into())).is_none());
        assert!(!valid_name("../escape"));
    }
}
