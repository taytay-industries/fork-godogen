# Recipe: 3D printing

Textures are wasted credits for printing — the print scenario generates bare geometry.

## FDM (single color, STL)

```bash
tripo make "a low-rise chess rook" --for print --json --yes
# → v3.1 bare geometry → convert STL + flatten_bottom
```

## Real-world size

```bash
tripo make "a phone stand" --for print \
  --then convert:format=STL,flatten_bottom=true,scale_factor=1.2 --json --yes
# or -p auto_size=true at generation for real-world meters
```

## Color print (3MF with vertex colors)

```bash
tripo make figurine.png --for print \
  --then "convert:format=3MF,export_vertex_colors=true" --json --yes
```

## Fix holes / make watertight first

```bash
tripo make broken.stl --then segment,complete,convert:stl --json --yes
```
