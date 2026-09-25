using Godot;

// Facing check: every GLB in a folder, unrotated, in a row, seen from +Z. Whatever faces the camera faces +Z.
// Generated models face different ways (Tripo image-to-model GLBs have come out facing +X and +Z); run this before
// placing a new batch, and set each model's yaw from it.
// Run: [FACING_DIR=res://assets/props] uv run tools/capture.py record --script tools/Facing.cs --seconds 0.2 --format png --out screenshots/facing
public partial class Facing : SceneTree
{
    public override void _Initialize()
    {
        var root = new Node3D();
        string dir = OS.GetEnvironment("FACING_DIR") is { Length: > 0 } d ? d : "res://assets";   // e.g. res://assets/parts
        var files = DirAccess.GetFilesAt(dir);
        float x = 0;
        foreach (var f in files)
        {
            if (!f.EndsWith(".glb")) continue;
            var m = GD.Load<PackedScene>($"{dir}/{f}").Instantiate<Node3D>();
            var box = Bounds(m, Transform3D.Identity);
            float s = 1.6f / Mathf.Max(box.Size.Y, Mathf.Max(box.Size.X, box.Size.Z));
            m.Scale = Vector3.One * s;
            m.Position = new Vector3(x - box.GetCenter().X * s, -box.Position.Y * s, -box.GetCenter().Z * s);
            root.AddChild(m);
            root.AddChild(new Label3D { Text = f.Replace(".glb", ""), Position = new Vector3(x, -0.25f, 0.5f), PixelSize = 0.004f, FontSize = 48 });
            x += 2f;
        }
        root.AddChild(new DirectionalLight3D { RotationDegrees = new Vector3(-40, 20, 0) });
        root.AddChild(new WorldEnvironment { Environment = new Godot.Environment { BackgroundMode = Godot.Environment.BGMode.Color, BackgroundColor = new Color(0.3f, 0.3f, 0.35f), AmbientLightSource = Godot.Environment.AmbientSource.Color, AmbientLightColor = Colors.White, AmbientLightEnergy = 0.6f } });
        var cam = new Camera3D { Projection = Camera3D.ProjectionType.Orthogonal, Size = x * 0.6f, Position = new Vector3(x / 2 - 1, 0.8f, 20) };
        root.AddChild(cam);
        GetRoot().AddChild(root);
    }

    static Aabb Bounds(Node n, Transform3D xf)
    {
        var box = new Aabb();
        bool any = false;
        void Walk(Node c, Transform3D t)
        {
            if (c is Node3D c3) t *= c3.Transform;
            if (c is MeshInstance3D mi && mi.Mesh != null) { var b = t * mi.GetAabb(); box = any ? box.Merge(b) : b; any = true; }
            foreach (var ch in c.GetChildren()) Walk(ch, t);
        }
        foreach (var ch in n.GetChildren()) Walk(ch, xf);
        return box;
    }
}
