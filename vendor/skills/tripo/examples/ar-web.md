# Recipe: AR / Web / e-commerce

iOS QuickLook needs USDZ; the web wants a small GLB. The ar-web scenario delivers both.

```bash
tripo make product.jpg --for ar-web --json --yes
# → v3.1 generate → decimate ≤20k faces (textures baked) → convert USDZ
# GLB comes from the decimate step; USDZ from convert. Both under output_dir.
```

Tighter mobile budget:

```bash
tripo make product.jpg --for ar-web --then decimate:8000,convert:usdz --json --yes
```

Web-only (skip USDZ):

```bash
tripo make product.jpg --then decimate:10000 --json --yes
```

Faithful textures from the photo: image inputs default to `texture_alignment=original_image` server-side; add `-p texture_alignment=geometry` only for stylized re-texturing.
