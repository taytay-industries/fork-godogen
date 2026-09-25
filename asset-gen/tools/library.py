#!/usr/bin/env python3
"""Search and download free (CC0) game assets: Poly Haven models, PBR textures and HDRI skies; ambientCG materials.

    library.py search "wooden chair" --kind model [--sheet refs/library/chairs.png]
    library.py search "wood floor" --kind texture
    library.py search "sunset" --kind hdri
    library.py get polyhaven:Rockingchair_01 -o assets/props/rocking_chair.glb      # model -> one .glb
    library.py get ambientcg:WoodFloor051 -o assets/textures/wood_floor/ --res 2k   # texture -> folder of maps
    library.py get polyhaven:kloppenheim_06 -o assets/sky/kloppenheim.hdr           # HDRI

`search` prints one line per candidate (id, name, real-world size, author); `--sheet` also writes a labeled
contact sheet of the thumbnails to look at before choosing. `get` writes the asset plus `<output>.source.json`
(source page, license, author) and logs both to the asset feed. Every asset here is CC0 — no attribution
required — but the author is recorded anyway. No keys needed.
"""
import argparse
import io
import json
import struct
import sys
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import feed

UA = {"User-Agent": "godogen-asset-library/1.0"}
CACHE = Path.home() / ".cache" / "godogen"
PH_TYPES = {"model": "models", "texture": "textures", "hdri": "hdris"}
ACG_TYPES = {"texture": "Material", "hdri": "HDRI"}
TEXTURE_MAPS = ("Diffuse", "nor_gl", "Rough", "AO", "arm", "Metal", "Displacement")   # Poly Haven map names


def fetch(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def fetch_json(url: str):
    return json.loads(fetch(url))


# --- search ---------------------------------------------------------------------------------------------------

def polyhaven_search(query: str, kind: str, limit: int) -> list[dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cache = CACHE / f"polyhaven_{PH_TYPES[kind]}.json"
    if not cache.exists() or time.time() - cache.stat().st_mtime > 86400:
        cache.write_bytes(fetch(f"https://api.polyhaven.com/assets?type={PH_TYPES[kind]}"))
    assets = json.loads(cache.read_text())
    terms = query.lower().split()
    hits = []
    for aid, a in assets.items():
        name = f"{aid} {a.get('name', '')}".lower()
        words = " ".join([name, *a.get("tags", []), *a.get("categories", [])]).lower()
        matched = sum(t in words for t in terms)
        if matched:   # most query words first, then words in the name, then popularity
            hits.append(((matched, sum(t in name for t in terms), a.get("download_count", 0)), aid, a))
    hits.sort(key=lambda h: h[0], reverse=True)
    out = []
    for _, aid, a in hits[:limit]:
        dims = a.get("dimensions")
        out.append({"id": f"polyhaven:{aid}", "name": a.get("name", aid), "kind": kind, "license": "CC0",
                    "author": ", ".join(a.get("authors", {})),
                    "size_m": [round(d / 1000, 2) for d in dims] if dims else None,     # Poly Haven gives mm
                    "thumb": f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=256&height=256",
                    "page": f"https://polyhaven.com/a/{aid}"})
    return out


def ambientcg_search(query: str, kind: str, limit: int) -> list[dict]:
    # ambientCG matches every word, so "lab floor tiles" finds nothing: fall back to fewer words until enough turn up.
    terms = query.split()
    tries = [terms] + [terms[:i] + terms[i + 1:] for i in range(len(terms))] + [[t] for t in reversed(terms)]
    found, seen = [], set()
    for t in tries:
        if not t or len(found) >= limit:
            continue
        q = urllib.parse.urlencode({"q": " ".join(t), "type": ACG_TYPES[kind], "include": "previewData,displayData",
                                    "limit": limit, "sort": "popular"})
        for a in fetch_json(f"https://ambientcg.com/api/v2/full_json?{q}").get("foundAssets", []):
            if a["assetId"] not in seen:
                seen.add(a["assetId"])
                found.append(a)
    out = []
    for a in found[:limit]:
        dims = [a.get(f"dimension{x}") for x in "XYZ"]
        out.append({"id": f"ambientcg:{a['assetId']}", "name": a.get("displayName", a["assetId"]), "kind": kind,
                    "license": "CC0", "author": "ambientCG",
                    "size_m": [round(d / 100, 2) for d in dims if d] or None,          # ambientCG gives cm
                    "thumb": a.get("previewImage", {}).get("256-PNG"),
                    "page": f"https://ambientcg.com/a/{a['assetId']}"})
    return out


SOURCES = {"polyhaven": (polyhaven_search, set(PH_TYPES)), "ambientcg": (ambientcg_search, set(ACG_TYPES))}


def contact_sheet(results: list[dict], out: Path, cols: int = 4, cell: int = 256):
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.load_default(size=15)
    rows = (len(results) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * (cell + 34)), (24, 26, 32))
    draw = ImageDraw.Draw(sheet)
    for i, r in enumerate(results):
        x, y = (i % cols) * cell, (i // cols) * (cell + 34)
        try:
            img = Image.open(io.BytesIO(fetch(r["thumb"], 20))).convert("RGBA")
            img.thumbnail((cell, cell))
            bg = Image.new("RGBA", img.size, (200, 200, 205, 255))
            sheet.paste(Image.alpha_composite(bg, img).convert("RGB"), (x + (cell - img.width) // 2, y))
        except Exception:
            draw.text((x + 8, y + cell // 2), "(no preview)", fill=(150, 150, 150))
        size = " x ".join(f"{d:g}" for d in r["size_m"]) + " m" if r.get("size_m") else ""
        draw.text((x + 6, y + cell + 1), f"{i + 1}. {r['id'].split(':', 1)[1]}"[:30], fill=(235, 235, 240), font=font)
        draw.text((x + 6, y + cell + 17), size, fill=(150, 200, 255), font=font)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out)


def cmd_search(a):
    sources = [a.source] if a.source else [s for s, (_, kinds) in SOURCES.items() if a.kind in kinds]
    results = []
    for s in sources:
        fn, kinds = SOURCES[s]
        if a.kind not in kinds:
            sys.exit(f"{s} has no {a.kind}s (it has: {', '.join(sorted(kinds))})")
        try:
            results += fn(a.query, a.kind, a.limit)
        except Exception as e:
            print(f"{s}: search failed: {e}", file=sys.stderr)
    # interleave sources so one library doesn't crowd out the other
    by = {s: [r for r in results if r["id"].startswith(s)] for s in sources}
    results = [r for group in zip(*[by[s] + [None] * a.limit for s in sources]) for r in group if r][:a.limit]
    if a.json:
        print(json.dumps(results, indent=1))
    else:
        for i, r in enumerate(results, 1):
            size = "×".join(f"{d:g}" for d in r["size_m"]) + " m" if r.get("size_m") else "-"
            print(f"{i:2}. {r['id']:<42} {r['name'][:34]:<34} {size:<18} {r['author'][:30]}")
    if a.sheet and results:
        sheet = Path(a.sheet)
        contact_sheet(results, sheet)
        print(f"sheet {sheet}", file=sys.stderr)
        job = feed.start(f"library search: {a.query}", tool=f"library ({', '.join(sources)})",
                         prompt=f'{a.kind}: "{a.query}" — {len(results)} candidates')
        feed.done(job, files=[sheet], log="\n".join(f"{i}. {r['id']}  {r['name']}" for i, r in enumerate(results, 1)))
    if not results:
        sys.exit(1)


# --- get ------------------------------------------------------------------------------------------------------

def pack_glb(gltf_path: Path, out: Path):
    """glTF + .bin + textures -> one self-contained .glb (what Godot, the feed and the game want)."""
    gltf = json.loads(gltf_path.read_text())
    base = gltf_path.parent
    blob = bytearray()

    def append(data: bytes) -> int:
        while len(blob) % 4:
            blob.append(0)
        start = len(blob)
        blob.extend(data)
        return start

    offsets = [append((base / urllib.parse.unquote(b["uri"])).read_bytes()) for b in gltf.get("buffers", [])]
    for bv in gltf.get("bufferViews", []):
        bv["byteOffset"] = bv.get("byteOffset", 0) + offsets[bv.get("buffer", 0)]
        bv["buffer"] = 0
    views = gltf.setdefault("bufferViews", [])
    for img in gltf.get("images", []):
        if "uri" in img:
            p = base / urllib.parse.unquote(img.pop("uri"))
            start = append(p.read_bytes())
            views.append({"buffer": 0, "byteOffset": start, "byteLength": p.stat().st_size})
            img["bufferView"] = len(views) - 1
            img["mimeType"] = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
    while len(blob) % 4:
        blob.append(0)
    gltf["buffers"] = [{"byteLength": len(blob)}]
    js = json.dumps(gltf, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "wb") as f:
        f.write(struct.pack("<4sII", b"glTF", 2, total))
        f.write(struct.pack("<I4s", len(js), b"JSON") + js)
        f.write(struct.pack("<I4s", len(blob), b"BIN\0") + bytes(blob))


def get_polyhaven(aid: str, out: Path, res: str) -> tuple[list[Path], dict]:
    info = fetch_json(f"https://api.polyhaven.com/info/{aid}")
    files = fetch_json(f"https://api.polyhaven.com/files/{aid}")
    kind = {0: "hdri", 1: "texture", 2: "model"}[info["type"]]
    meta = {"source": "Poly Haven", "id": aid, "name": info.get("name", aid), "kind": kind, "license": "CC0",
            "author": ", ".join(info.get("authors", {})), "page": f"https://polyhaven.com/a/{aid}", "res": res,
            "thumb": f"https://cdn.polyhaven.com/asset_img/thumbs/{aid}.png?width=512&height=512"}
    if kind == "model":
        if out.suffix.lower() != ".glb":
            sys.exit("a model downloads as one .glb: give -o something.glb")
        g = files["gltf"][res]["gltf"]
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / Path(g["url"]).name
            src.write_bytes(fetch(g["url"]))
            for rel, f in g.get("include", {}).items():
                (Path(tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
                (Path(tmp) / rel).write_bytes(fetch(f["url"]))
            pack_glb(src, out)
        if info.get("dimensions"):
            meta["size_m"] = [round(d / 1000, 3) for d in info["dimensions"]]
        return [out], meta
    if kind == "hdri":
        fmt = out.suffix.lower().lstrip(".")
        if fmt not in ("hdr", "exr"):
            sys.exit("an HDRI downloads as one file: give -o something.hdr (or .exr)")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(fetch(files["hdri"][res][fmt]["url"]))
        return [out], meta
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for m in TEXTURE_MAPS:
        f = files.get(m, {}).get(res, {}).get("jpg") or files.get(m, {}).get(res, {}).get("png")
        if f:
            p = out / Path(f["url"]).name
            p.write_bytes(fetch(f["url"]))
            written.append(p)
    return written, meta


def get_ambientcg(aid: str, out: Path, res: str) -> tuple[list[Path], dict]:
    q = urllib.parse.urlencode({"id": aid, "include": "downloadData,displayData"})
    found = fetch_json(f"https://ambientcg.com/api/v2/full_json?{q}")["foundAssets"]
    if not found:
        sys.exit(f"ambientCG has no asset {aid}")
    a = found[0]
    want = f"{res.upper()}-JPG"
    dls = a["downloadFolders"]["default"]["downloadFiletypeCategories"]["zip"]["downloads"]
    dl = next((d for d in dls if d["attribute"] == want), None) or next((d for d in dls if "JPG" in d["attribute"]), dls[0])
    out.mkdir(parents=True, exist_ok=True)
    written = []
    with zipfile.ZipFile(io.BytesIO(fetch(dl["downloadLink"], 300))) as z:
        for n in z.namelist():
            # the maps only: not the zip's preview render (<id>.png) or the DirectX normal map Godot doesn't use
            if Path(n).suffix.lower() in (".jpg", ".png") and Path(n).stem != aid and "NormalDX" not in n:
                p = out / Path(n).name
                p.write_bytes(z.read(n))
                written.append(p)
    meta = {"source": "ambientCG", "id": aid, "name": a.get("displayName", aid), "kind": a.get("dataTypeName", "Material"),
            "license": "CC0", "author": "ambientCG", "page": f"https://ambientcg.com/a/{aid}", "res": dl["attribute"],
            "thumb": f"https://acg-media.struffelproductions.com/file/ambientCG-Web/media/thumbnail/512-PNG/{aid}.png"}
    return written, meta


def cmd_get(a):
    source, _, aid = a.id.partition(":")
    getter = {"polyhaven": get_polyhaven, "ambientcg": get_ambientcg}.get(source)
    if not getter or not aid:
        sys.exit("id must be polyhaven:<id> or ambientcg:<id> (as printed by search)")
    out = Path(a.output)
    job = feed.start(out.name, tool=f"library ({source})", prompt=f"{a.id}", eta=15)
    try:
        written, meta = getter(aid, out, a.res)
    except Exception as e:
        feed.done(job, ok=False, error=f"{type(e).__name__}: {e}")
        raise
    record = out.with_name(out.name.rstrip("/") + ".source.json") if out.suffix else out / "source.json"
    record.write_text(json.dumps(meta, indent=1) + "\n")
    # The feed card shows the source's own preview beside what landed in the project (an .hdr has no browser view).
    preview = Path("refs/library") / f"{source}_{aid}.png"
    try:
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_bytes(fetch(meta["thumb"], 20))
    except Exception:
        preview = None
    feed.done(job, files=[*written, preview], log=f"{meta['name']} — {meta['license']}, by {meta['author']}\n{meta['page']}")
    print(json.dumps({"ok": True, "files": [str(p) for p in written], "source": str(record), **meta}))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    s = sub.add_parser("search", help="find candidates")
    s.add_argument("query")
    s.add_argument("--kind", choices=["model", "texture", "hdri"], required=True)
    s.add_argument("--source", choices=sorted(SOURCES))
    s.add_argument("--limit", type=int, default=12)
    s.add_argument("--sheet", help="write a labeled contact sheet of the thumbnails here")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)
    g = sub.add_parser("get", help="download one asset into the project")
    g.add_argument("id", help="polyhaven:<id> or ambientcg:<id>, as printed by search")
    g.add_argument("-o", "--output", required=True, help="model: a .glb path · texture: a folder · hdri: a .hdr/.exr path")
    g.add_argument("--res", default="1k", help="1k, 2k, 4k (default 1k)")
    g.set_defaults(func=cmd_get)
    a = ap.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
