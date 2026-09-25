using Godot;
using System.Collections.Generic;

// Shared scene-builder helpers (for the SceneTree builders in scenes/): GLB placement scaled from the model's measured
// bounds, boxes with and without collision, and the owner-chain + pack-validate save from godot.md.
//   var kit = new SceneKit(); kit.Add("desk", new SceneKit.Model("props/desk", 1.6f, ByHeight: false));
//   root.AddChild(kit.Place("desk", new Vector3(2, 0, -1), yaw: 90, name: "Desk"));   ...   SceneKit.PackAndSave(root, "res://scenes/lab.tscn");
public class SceneKit
{
    // Size is the height when ByHeight, else the longest horizontal extent. Yaw turns the GLB's front to +Z
    // (a model facing +X needs -90; check with tools/Facing.cs).
    public record Model(string File, float Size, bool ByHeight = true, float Yaw = 0f);

    readonly Dictionary<string, Model> _models = new();
    readonly Dictionary<string, (PackedScene scene, float scale, Vector3 offset, Vector3 size)> _cache = new();

    public void Add(string name, Model m) => _models[name] = m;

    // A wrapper at `pos` holding the model scaled, grounded (its bottom at the wrapper's origin) and centered;
    // optionally a StaticBody with a box collider. The measured size is stored as meta "size".
    public Node3D Place(string model, Vector3 pos, float yaw, string name, bool collide = true)
    {
        Node3D wrap = collide ? new StaticBody3D() : new Node3D();
        wrap.Name = name;
        wrap.Position = pos;
        wrap.RotationDegrees = new Vector3(0, yaw, 0);
        var (scene, scale, offset, size) = Measure(model);
        var inst = scene.Instantiate<Node3D>();
        inst.Name = "Model";
        inst.Scale = Vector3.One * scale;
        inst.RotationDegrees = new Vector3(0, _models[model].Yaw, 0);
        inst.Position = offset;
        wrap.AddChild(inst);
        wrap.SetMeta("size", size);
        if (collide)
            wrap.AddChild(new CollisionShape3D { Name = "Shape", Shape = new BoxShape3D { Size = size }, Position = new Vector3(0, size.Y / 2, 0) });
        return wrap;
    }

    public (PackedScene scene, float scale, Vector3 offset, Vector3 size) Measure(string model)
    {
        if (_cache.TryGetValue(model, out var c)) return c;
        var m = _models[model];
        var scene = GD.Load<PackedScene>($"res://assets/{m.File}.glb");
        var probe = scene.Instantiate<Node3D>();
        var box = new Aabb();
        bool any = false;
        foreach (var ch in probe.GetChildren()) MergeBounds(ch, Transform3D.Identity, ref box, ref any);
        probe.Free();
        var rotated = new Transform3D(new Basis(Vector3.Up, Mathf.DegToRad(m.Yaw)), Vector3.Zero) * box;
        float s = m.ByHeight ? m.Size / rotated.Size.Y : m.Size / Mathf.Max(rotated.Size.X, rotated.Size.Z);
        var center = rotated.GetCenter();
        var offset = new Vector3(-center.X, -rotated.Position.Y, -center.Z) * s;
        GD.Print($"{model}: size {rotated.Size * s}");
        return _cache[model] = (scene, s, offset, rotated.Size * s);
    }

    static void MergeBounds(Node n, Transform3D xf, ref Aabb box, ref bool any)
    {
        if (n is Node3D n3) xf *= n3.Transform;
        if (n is MeshInstance3D mi && mi.Mesh != null)
        {
            var b = xf * mi.GetAabb();
            box = any ? box.Merge(b) : b;
            any = true;
        }
        foreach (var ch in n.GetChildren()) MergeBounds(ch, xf, ref box, ref any);
    }

    public static void Slab(Node3D parent, string name, Vector3 pos, Vector3 size, Material mat)
    {
        var body = new StaticBody3D { Name = name, Position = pos };
        body.AddChild(new MeshInstance3D { Name = "Mesh", Mesh = new BoxMesh { Size = size, Material = mat } });
        body.AddChild(new CollisionShape3D { Name = "Shape", Shape = new BoxShape3D { Size = size } });
        parent.AddChild(body);
    }

    public static MeshInstance3D Deco(Node3D parent, string name, Vector3 pos, Vector3 size, Material mat)
    {
        var m = new MeshInstance3D { Name = name, Mesh = new BoxMesh { Size = size, Material = mat }, Position = pos };
        parent.AddChild(m);
        return m;
    }

    public static ImageTexture TileTexture(Color face, Color line)
    {
        var img = Image.CreateEmpty(128, 128, true, Image.Format.Rgb8);
        for (int y = 0; y < 128; y++)
            for (int x = 0; x < 128; x++)
                img.SetPixel(x, y, x < 2 || y < 2 ? line : face);
        img.GenerateMipmaps();
        return ImageTexture.CreateFromImage(img);
    }

    // Owner chain (never into instanced GLBs), then pack, re-instantiate, and refuse to save on a node drop.
    public static bool PackAndSave(Node root, string path)
    {
        SetOwnerRecursive(root, root);
        int expected = CountNodes(root);
        var packed = new PackedScene();
        if (packed.Pack(root) != Error.Ok) return false;
        var test = packed.Instantiate();
        int got = CountNodes(test);
        test.Free();
        if (got < expected) { GD.PushError($"nodes dropped: {got}/{expected}"); return false; }
        ResourceSaver.Save(packed, path);
        GD.Print($"saved {path} ({got} nodes)");
        return true;
    }

    static void SetOwnerRecursive(Node n, Node owner)
    {
        foreach (var ch in n.GetChildren())
        {
            ch.Owner = owner;
            if (string.IsNullOrEmpty(ch.SceneFilePath)) SetOwnerRecursive(ch, owner);
        }
    }

    static int CountNodes(Node n)
    {
        int count = 1;
        foreach (var ch in n.GetChildren())
            count += string.IsNullOrEmpty(ch.SceneFilePath) ? CountNodes(ch) : 1;
        return count;
    }
}
