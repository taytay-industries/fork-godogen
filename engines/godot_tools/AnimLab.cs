using Godot;
using System;
using System.Collections.Generic;
using System.Linq;
using System.Text;

// AnimLab — inspect a rigged character's animation clips in isolation.
//
//   uv run tools/capture.py record --script tools/AnimLab.cs --out screenshots/animlab --seconds 12 -- ++ \
//       --model res://assets/villager_a.glb --anim res://assets/villager_a_walk.glb --clip walk,idle
//
// Args (after ++):
//   --model PATH     rigged GLB (required)
//   --anim PATH      extra GLB whose clips are merged in (same rig); repeatable
//   --clip A,B       clips to show, in order (default: all)
//   --cycles N       loops shown per clip (default 3)
//   --height M       scale the character to this height in meters (default 1.7)
//   --strip-root     remove the Hip's forward drift before analysis (as the game would)
//   --report PATH    JSON report (default res://screenshots/animlab/report.json)
//   --yaw DEG        display yaw for the character (default: turn the first travelling clip to face +Z)
//   --strip-root-local  the naive strip (in Hip-local space, ignoring the parent bone's rotation) — for comparison
//   --game-forward AX   move the character the way the game does: along model axis AX (+Z, -Z, +X, -X) at the
//                       clip's speed, instead of along its feet. Feet that push another way slip (crab walk).
//   --export PATH.glb   after the fixes and analysis, write a clean GLB: the listed clips merged, fixes baked in,
//                       turned so the walk travels +Z, scaled to --height meters; plus PATH.json (clip lengths,
//                       authored speeds). Nothing is written if any clip FAILs. Re-check the result with no fix flags.
//   --fix-loop       remove the importer's duplicated first key (Tripo clips: legs freeze + body slips back each loop)
//   --loop           keep cycling through the clips until the window is closed (interactive viewing)
//
// Before playback each clip is sampled at 120 Hz from the skeleton and measured; FAIL findings
// are pushed as errors so capture.py lists them. The floor is a treadmill moving at the clip's
// own ground speed (measured from planted feet), so a planted foot should stay on its footprint.
public partial class AnimLab : SceneTree
{
    const float SampleHz = 120f;
    const float PlantMargin = 0.02f;   // a foot within 2 cm of its lowest point, not rising or falling, is planted

    record Opts(string Model, List<string> Anims, List<string> Clips, int Cycles, float Height, bool StripRoot, string Report, bool Loop, float Yaw, bool FixLoop, bool StripLocal, string GameForward, string Export);

    class Metrics
    {
        public string Clip;
        public float Sway, LateralSlideMax;
        // Per foot, one cycle: heel/toe height above their rest-pose height (0 = touching the floor) and plant flags.
        public Dictionary<string, float[]> Heel = new(), Toe = new();
        public Dictionary<string, bool[]> Plant = new();
        public float Length, Drift, DriftSpeed, GroundSpeed, SeamRatio, SeamStep, MedianStep, HipBob;
        public Vector3 GroundVel, DriftVec, TravelVec;
        public string Travel = "in place";
        public float TravelYaw = float.NaN;   // model-space heading of travel, degrees from +Z
        public float PhaseOffset = -1;
        public Dictionary<string, float> FootAbsMin = new();
        public Dictionary<string, float> FootMin = new(), FootPlanted = new(), SlideMax = new(), SlideMean = new();
        public List<string> Spikes = new(), Stretch = new(), Plants = new();
        public int Strides = 1;
        public List<(string foot, float heelLow)> PlantHeels = new();
        public float[] Steps;          // pose change per sample (max bone movement), one cycle
        public float StallMs, StallPhase = -1, StepsMedian, LocalMedian;
        public float[] LocalSteps, BodySpeed;
        public float BodyMin, BodyMinPhase;
        public List<(string level, string text)> Findings = new();
    }

    Opts _o;
    Node3D _world, _holder, _ground;
    AnimationPlayer _anim;
    Skeleton3D _skel;
    int _hip, _hipPrev = -1;
    readonly List<(string name, int foot, int toe)> _feet = new();
    readonly Dictionary<string, float> _footRest = new();
    readonly Dictionary<string, float> _heelRest = new(), _toeRest = new();
    Control _graph;   // foot contact height in the rest pose (sole on the floor)
    float _facingYaw;   // yaw applied to the character so its travel direction faces +Z
    readonly List<Metrics> _results = new();
    int _clipIndex = -1;
    double _clipTime;
    Metrics _cur;
    Label _hud, _title;
    ShaderMaterial _gridMat;
    MeshInstance3D _bonesMesh, _trailMesh;
    readonly Dictionary<string, List<Vector3>> _trails = new();
    readonly Dictionary<string, bool> _wasPlanted = new();
    readonly Dictionary<string, (Node3D mark, Vector3 at)> _lastPrint = new();
    readonly StandardMaterial3D _lineMat = new()
    {
        ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded,
        VertexColorUseAsAlbedo = true,
        NoDepthTest = true,
        Transparency = BaseMaterial3D.TransparencyEnum.Alpha,
    };

    public override void _Initialize()
    {
        _o = ParseArgs();
        if (_o == null) { Quit(2); return; }
        BuildStage();
        if (!LoadCharacter()) { Quit(2); return; }
    }

    // Bone poses only resolve once the stage is inside the tree, so analysis waits for the first frame.
    // Writes the fixed character as a new GLB: a fresh instance of the model with the (already fixed) clips, the
    // yaw that makes its travel face +Z, and the scale that makes it --height tall, all on a wrapper node.
    void Export()
    {
        var failed = _results.Where(r => r.Findings.Any(f => f.level == "FAIL")).Select(r => r.Clip).ToList();
        if (failed.Count > 0) { GD.PushError($"AnimLab: not exporting — FAIL in {string.Join(", ", failed)}"); return; }

        var model = GD.Load<PackedScene>(_o.Model).Instantiate<Node3D>();
        var player = Find<AnimationPlayer>(model);
        var lib = new AnimationLibrary();
        foreach (var c in _o.Clips) lib.AddAnimation(c, _anim.GetAnimation(c));   // the fixed clips
        foreach (var name in player.GetAnimationLibraryList()) player.RemoveAnimationLibrary(name);
        player.AddAnimationLibrary("", lib);

        var mover = _results.FirstOrDefault(r => !float.IsNaN(r.TravelYaw));
        float yaw = mover != null ? -mover.TravelYaw : 0f;
        var box = new Aabb(); bool any = false;
        MergeBounds(model, Transform3D.Identity, ref box, ref any);
        float scale = _o.Height / Mathf.Max(box.Size.Y, 0.001f);
        string name0 = System.IO.Path.GetFileNameWithoutExtension(_o.Export);
        var root = new Node3D { Name = name0 };
        var fit = new Node3D
        {
            Name = "Fit",
            Scale = Vector3.One * scale,
            Rotation = new Vector3(0, Mathf.DegToRad(yaw), 0),
            Position = new Vector3(0, -box.Position.Y * scale, 0),
        };
        root.AddChild(fit);
        fit.AddChild(model);
        _world.AddChild(root);   // skeleton and player resolve inside the tree
        player.Stop();
        Find<Skeleton3D>(model)?.ResetBonePoses();

        var doc = new GltfDocument();
        var state = new GltfState();
        var err = doc.AppendFromScene(root, state);
        var path = ProjectSettings.GlobalizePath(_o.Export);
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path));
        if (err == Error.Ok) err = doc.WriteToFilesystem(state, path);
        _world.RemoveChild(root);
        root.QueueFree();
        if (err != Error.Ok) { GD.PushError($"AnimLab: export failed: {err}"); return; }
        // Godot's exporter re-encodes every texture from the imported image; the export only changes animation and
        // node transforms, so put the source GLB's original image bytes back.
        int copied = GlbTextures.CopyFrom(ProjectSettings.GlobalizePath(_o.Model), path);
        GD.Print($"AnimLab: {copied} texture(s) copied byte-for-byte from the source GLB");

        var inv = System.Globalization.CultureInfo.InvariantCulture;
        var clips = string.Join(",\n", _results.Select(r =>
            $"    \"{r.Clip}\": {{\"length_s\": {r.Length.ToString("0.####", inv)}, \"loop\": true, \"ground_speed_mps\": {(r.GroundSpeed > 0.1f ? r.GroundSpeed : 0).ToString("0.###", inv)}}}"));
        System.IO.File.WriteAllText(System.IO.Path.ChangeExtension(path, ".json"),
            "{\n  \"source\": \"" + _o.Model + "\",\n  \"height_m\": " + _o.Height.ToString(inv) + ",\n  \"forward\": \"+Z\",\n" +
            "  \"fixes\": [" + string.Join(", ", new[] { _o.FixLoop ? "\"loop starts at 0\"" : null, _o.StripRoot ? "\"root drift removed (parent frame)\"" : null, mover != null ? $"\"turned {yaw:0}° so travel is +Z\"" : null }.Where(x => x != null)) + "],\n" +
            "  \"clips\": {\n" + clips + "\n  }\n}\n");
        GD.Print($"AnimLab: exported {path} (+ .json): clips [{string.Join(", ", _o.Clips)}], yaw {yaw:0}°, scale {scale:0.###}");
    }

    static Vector3? Axis(string a) => a switch { "+Z" or "Z" => Vector3.Back, "-Z" => Vector3.Forward, "+X" or "X" => Vector3.Right, "-X" => Vector3.Left, _ => null };

    void AnalyzeAll()
    {
        foreach (var clip in _o.Clips) _results.Add(Analyze(clip));
        var game = _o.GameForward != null ? Axis(_o.GameForward) : null;
        if (_o.GameForward != null && game == null) GD.PushError($"AnimLab: --game-forward must be +Z, -Z, +X or -X (got {_o.GameForward})");
        if (game is { } g)
            foreach (var r in _results.Where(r => r.GroundSpeed > 0.1f))
            {
                // The game carries the character along its axis at the clip's speed; the feet push along the clip's own travel.
                var feet = -r.GroundVel + r.DriftVec / r.Length;
                var slip = (feet - g * feet.Length()).Length();
                r.Findings.RemoveAll(f => f.level == "PASS");
                r.Findings.RemoveAll(f => f.text.StartsWith("clip travels"));
                if (slip > 0.1f * r.GroundSpeed)
                    r.Findings.Insert(0, ("FAIL", $"the game moves it along model {_o.GameForward} but the feet push {r.Travel}: planted feet slip {slip:0.00} m/s ({Mathf.RadToDeg(g.SignedAngleTo(feet, Vector3.Up)):0}° off) — it will crab-walk"));
                else
                    r.Findings.Insert(0, ("PASS", $"game forward {_o.GameForward} matches the clip's travel ({r.Travel})"));
            }
        WriteReport();
        if (_o.Export != null) Export();
        // Display: turn the character so its travel (or the game's forward) runs across the SIDE view.
        var mover = _results.FirstOrDefault(r => !float.IsNaN(r.TravelYaw));
        if (!float.IsNaN(_o.Yaw) || mover != null || game != null)
        {
            _facingYaw = !float.IsNaN(_o.Yaw) ? _o.Yaw
                : game is { } ga ? -Mathf.RadToDeg(Mathf.Atan2(ga.X, ga.Z))
                : -mover.TravelYaw;
            _holder.RotationDegrees = new Vector3(0, _facingYaw, 0);
            var turn = new Basis(Vector3.Up, Mathf.DegToRad(_facingYaw));
            foreach (var r in _results)
                r.GroundVel = game is { } gv && r.GroundSpeed > 0.1f ? turn * (-gv * r.GroundSpeed) : turn * r.GroundVel;
        }
        NextClip();
    }

    // ---------------------------------------------------------------- setup

    static Opts ParseArgs()
    {
        var a = OS.GetCmdlineUserArgs();
        string model = null, report = "res://screenshots/animlab/report.json";
        var anims = new List<string>();
        var clips = new List<string>();
        int cycles = 3; float height = 1.7f, yaw = float.NaN; bool strip = false, loop = false, fixLoop = false, stripLocal = false; string gameForward = null, export = null;
        for (int i = 0; i < a.Length; i++)
        {
            string Next() => i + 1 < a.Length ? a[++i] : "";
            switch (a[i])
            {
                case "--model": model = Next(); break;
                case "--anim": anims.Add(Next()); break;
                case "--clip": clips.AddRange(Next().Split(',', StringSplitOptions.RemoveEmptyEntries)); break;
                case "--cycles": cycles = int.Parse(Next()); break;
                case "--height": height = float.Parse(Next(), System.Globalization.CultureInfo.InvariantCulture); break;
                case "--strip-root": strip = true; break;
                case "--report": report = Next(); break;
                case "--loop": loop = true; break;
                case "--fix-loop": fixLoop = true; break;
                case "--game-forward": gameForward = Next().ToUpperInvariant(); break;
                case "--export": export = Next(); break;
                case "--strip-root-local": strip = true; stripLocal = true; break;
                case "--yaw": yaw = float.Parse(Next(), System.Globalization.CultureInfo.InvariantCulture); break;
            }
        }
        if (model == null) { GD.PushError("AnimLab: --model res://path.glb is required (pass args after ++)"); return null; }
        return new Opts(model, anims, clips, cycles, height, strip, report, loop, yaw, fixLoop, stripLocal, gameForward, export);
    }

    void BuildStage()
    {
        _world = new Node3D { Name = "AnimLab" };
        Root.AddChild(_world);

        var env = new Godot.Environment
        {
            BackgroundMode = Godot.Environment.BGMode.Color,
            BackgroundColor = new Color(0.16f, 0.17f, 0.2f),
            AmbientLightSource = Godot.Environment.AmbientSource.Color,
            AmbientLightColor = new Color(0.8f, 0.82f, 0.9f),
            AmbientLightEnergy = 0.6f,
            TonemapMode = Godot.Environment.ToneMapper.Filmic,
        };
        _world.AddChild(new WorldEnvironment { Environment = env });
        _world.AddChild(new DirectionalLight3D { RotationDegrees = new Vector3(-50, -30, 0), LightEnergy = 1.1f, ShadowEnabled = true });

        _ground = new Node3D { Name = "Ground" };
        _world.AddChild(_ground);
        _gridMat = new ShaderMaterial { Shader = new Shader { Code = GridShader } };
        _world.AddChild(new MeshInstance3D { Mesh = new PlaneMesh { Size = new Vector2(40, 40), Material = _gridMat } });

        _trailMesh = new MeshInstance3D { Mesh = new ImmediateMesh(), CastShadow = GeometryInstance3D.ShadowCastingSetting.Off };
        _ground.AddChild(_trailMesh);
        _bonesMesh = new MeshInstance3D { Mesh = new ImmediateMesh(), CastShadow = GeometryInstance3D.ShadowCastingSetting.Off };
        _world.AddChild(_bonesMesh);

        // Three views of one world: side (large), front, and a 3/4 perspective.
        var ui = new Control();
        ui.SetAnchorsPreset(Control.LayoutPreset.FullRect);
        var layer = new CanvasLayer();
        _world.AddChild(layer);
        layer.AddChild(ui);
        View(ui, "SIDE", new Rect2(0, 0, 0.6f, 0.7f), cam =>
        {
            cam.Projection = Camera3D.ProjectionType.Orthogonal;
            cam.Size = _o.Height * 1.3f;
            cam.Position = new Vector3(-8, _o.Height * 0.52f, 0);
            cam.RotationDegrees = new Vector3(0, -90, 0);
        });
        View(ui, "FRONT", new Rect2(0.6f, 0, 0.4f, 0.5f), cam =>
        {
            cam.Projection = Camera3D.ProjectionType.Orthogonal;
            cam.Size = _o.Height * 1.3f;
            cam.Position = new Vector3(0, _o.Height * 0.52f, 8);
        });
        View(ui, "3/4", new Rect2(0.6f, 0.5f, 0.4f, 0.5f), cam =>
        {
            cam.Fov = 40;
            cam.Position = new Vector3(3.2f, _o.Height * 1.25f, 3.6f);
            cam.LookAtFromPosition(cam.Position, new Vector3(0, _o.Height * 0.45f, 0));
        });

        _title = new Label
        {
            Position = new Vector2(24, 18),
            LabelSettings = new LabelSettings { FontSize = 40, OutlineSize = 8, OutlineColor = new Color(0, 0, 0, 0.7f), FontColor = new Color(1f, 0.92f, 0.55f) },
        };
        ui.AddChild(_title);
        var panel = new ColorRect { Color = new Color(0.08f, 0.085f, 0.1f) };
        panel.AnchorTop = 0.7f; panel.AnchorRight = 0.6f; panel.AnchorBottom = 1f;
        ui.AddChild(panel);
        _hud = new Label
        {
            Position = new Vector2(20, 12),
            LabelSettings = new LabelSettings { FontSize = 21, FontColor = new Color(0.92f, 0.93f, 0.95f), LineSpacing = 1 },
        };
        _hud.AutowrapMode = TextServer.AutowrapMode.WordSmart;
        _hud.AnchorRight = 0.5f; _hud.OffsetRight = 0;
        panel.AddChild(_hud);
        _graph = new Control();
        _graph.AnchorLeft = 0.52f; _graph.AnchorTop = 0.06f; _graph.AnchorRight = 0.985f; _graph.AnchorBottom = 0.94f;
        _graph.Draw += DrawGraph;
        panel.AddChild(_graph);
    }

    void View(Control ui, string title, Rect2 frac, Action<Camera3D> setup)
    {
        var box = new SubViewportContainer { Stretch = true };
        box.AnchorLeft = frac.Position.X; box.AnchorTop = frac.Position.Y;
        box.AnchorRight = frac.End.X; box.AnchorBottom = frac.End.Y;
        var vp = new SubViewport { Msaa3D = Viewport.Msaa.Msaa4X };
        var cam = new Camera3D { Current = true };
        vp.AddChild(cam);
        box.AddChild(vp);
        ui.AddChild(box);
        setup(cam);
        var tag = new Label
        {
            Text = title,
            LabelSettings = new LabelSettings { FontSize = 22, FontColor = new Color(1, 1, 1, 0.55f) },
            Position = new Vector2(12, 8),
        };
        box.AddChild(tag);
    }

    bool LoadCharacter()
    {
        if (!ResourceLoader.Exists(_o.Model)) { GD.PushError($"AnimLab: no such model {_o.Model}"); return false; }
        var model = GD.Load<PackedScene>(_o.Model).Instantiate<Node3D>();
        _holder = new Node3D { Name = "Character" };
        _holder.AddChild(model);
        _world.AddChild(_holder);

        _anim = Find<AnimationPlayer>(model);
        _skel = Find<Skeleton3D>(model);
        if (_skel == null) { GD.PushError("AnimLab: model has no Skeleton3D"); return false; }

        foreach (var path in _o.Anims)
        {
            var donor = GD.Load<PackedScene>(path).Instantiate();
            var dp = Find<AnimationPlayer>(donor);
            if (_anim == null && dp != null)
            {
                // A bare rig (Tripo's rig output has no clips): give it a player whose root matches the donor's,
                // so the donor's track paths resolve on this model.
                _anim = new AnimationPlayer { Name = "AnimationPlayer" };
                model.AddChild(_anim);
                var rootPath = donor.GetPathTo(dp.GetNode(dp.RootNode));
                _anim.RootNode = _anim.GetPathTo(rootPath.IsEmpty || rootPath.ToString() == "." ? model : model.GetNode(rootPath));
            }
            if (_anim == null) { donor.Free(); continue; }
            if (!_anim.HasAnimationLibrary("")) _anim.AddAnimationLibrary("", new AnimationLibrary());
            var lib = _anim.GetAnimationLibrary("");
            foreach (var n in dp?.GetAnimationList() ?? Array.Empty<string>())
            {
                string name = _anim.HasAnimation(n) ? $"{n}_{System.IO.Path.GetFileNameWithoutExtension(path)}" : n;
                lib.AddAnimation(name, dp.GetAnimation(n));
            }
            donor.Free();
        }
        if (_anim == null) { GD.PushError("AnimLab: no clips — the model has no AnimationPlayer and no --anim GLB supplied one"); return false; }
        if (_o.Clips.Count == 0) _o.Clips.AddRange(_anim.GetAnimationList());
        foreach (var c in _o.Clips.ToList())
            if (!_anim.HasAnimation(c)) { GD.PushError($"AnimLab: no clip '{c}' (have: {string.Join(", ", _anim.GetAnimationList())})"); _o.Clips.Remove(c); }
        if (_o.Clips.Count == 0) return false;

        // Scale to height and seat on the floor from the rest-pose bounds.
        var box = new Aabb(); bool any = false;
        MergeBounds(model, Transform3D.Identity, ref box, ref any);
        float s = _o.Height / Mathf.Max(box.Size.Y, 0.001f);
        model.Scale = Vector3.One * s;
        model.Position = new Vector3(0, -box.Position.Y * s, 0);

        _hip = FindBone("hip", "pelvis", "hips", "root");
        if (_hip >= 0) _hipPrev = _skel.GetBoneParent(_hip);
        foreach (var side in new[] { "L", "R" })
        {
            int foot = FindSided(side, "foot", "ankle"), toe = FindSided(side, "toe", "ball");
            if (foot >= 0) _feet.Add((side, foot, toe));
        }
        GD.Print($"AnimLab: {_o.Model} scale {s:0.###}, hip={(_hip >= 0 ? _skel.GetBoneName(_hip) : "?")}, feet={string.Join(",", _feet.Select(f => _skel.GetBoneName(f.foot)))}, clips=[{string.Join(", ", _anim.GetAnimationList())}]");

        foreach (var (name, foot, toe) in _feet)
        {
            float Rest(int b) => (_skel.GetBoneGlobalRest(b).Origin * s).Y + model.Position.Y;
            _footRest[name] = toe >= 0 ? Mathf.Min(Rest(foot), Rest(toe)) : Rest(foot);
            _heelRest[name] = Rest(foot);
            _toeRest[name] = toe >= 0 ? Rest(toe) : Rest(foot);
        }
        foreach (var c in _o.Clips)
        {
            var clip = _anim.GetAnimation(c);
            clip.LoopMode = Animation.LoopModeEnum.Linear;
            if (_o.FixLoop && NormalizeLoop(clip)) GD.Print($"AnimLab [{c}] removed the importer's duplicated first key -> length {clip.Length:0.####}s");
            if (_o.StripLocal) StripRootMotionLocal(clip);
            else if (_o.StripRoot) StripRootMotion(clip, _skel);
        }
        return true;
    }

    int FindBone(params string[] keys)
    {
        foreach (var k in keys)
            for (int i = 0; i < _skel.GetBoneCount(); i++)
                if (_skel.GetBoneName(i).ToLowerInvariant() == k) return i;
        foreach (var k in keys)
            for (int i = 0; i < _skel.GetBoneCount(); i++)
                if (_skel.GetBoneName(i).ToLowerInvariant().Contains(k)) return i;
        return -1;
    }

    int FindSided(string side, params string[] keys)
    {
        string s = side.ToLowerInvariant(), word = side == "L" ? "left" : "right";
        for (int i = 0; i < _skel.GetBoneCount(); i++)
        {
            var n = _skel.GetBoneName(i).ToLowerInvariant();
            bool sided = n.StartsWith(s + "_") || n.StartsWith(word) || n.EndsWith("_" + s) || n.EndsWith("." + s) || n.Contains(word);
            if (sided && keys.Any(k => n.Contains(k)) && !n.Contains("twist")) return i;
        }
        return -1;
    }

    // ---------------------------------------------------------------- analysis

    Vector3 BoneWorld(int b) => _skel.GlobalTransform * _skel.GetBoneGlobalPose(b).Origin;

    float FootHeight(int foot, int toe) => toe >= 0 ? Mathf.Min(BoneWorld(foot).Y, BoneWorld(toe).Y) : BoneWorld(foot).Y;

    Vector3 FootPoint(int foot, int toe) => toe >= 0 ? (BoneWorld(foot) + BoneWorld(toe)) * 0.5f : BoneWorld(foot);

    Metrics Analyze(string clipName)
    {
        var clip = _anim.GetAnimation(clipName);
        var m = new Metrics { Clip = clipName, Length = (float)clip.Length };
        int n = Mathf.Max(8, Mathf.CeilToInt(m.Length * SampleHz));
        float dt = m.Length / n;
        int bones = _skel.GetBoneCount();
        var pos = new Vector3[n, bones];
        var footH = new float[_feet.Count, n];
        var footP = new Vector3[_feet.Count, n];
        foreach (var (name, _, _) in _feet) { m.Heel[name] = new float[n]; m.Toe[name] = new float[n]; m.Plant[name] = new bool[n]; }

        _anim.Play(clipName);
        for (int k = 0; k < n; k++)
        {
            _anim.Seek(k * dt, true);
            for (int b = 0; b < bones; b++) pos[k, b] = BoneWorld(b);
            for (int f = 0; f < _feet.Count; f++)
            {
                footH[f, k] = FootHeight(_feet[f].foot, _feet[f].toe);
                footP[f, k] = FootPoint(_feet[f].foot, _feet[f].toe);
                var (nm, fb, tb) = _feet[f];
                m.Heel[nm][k] = BoneWorld(fb).Y - _heelRest[nm];
                m.Toe[nm][k] = (tb >= 0 ? BoneWorld(tb).Y : BoneWorld(fb).Y) - _toeRest[nm];
            }
        }

        // Root drift across one cycle (hip, horizontal).
        if (_hip >= 0)
        {
            m.DriftVec = pos[n - 1, _hip] - pos[0, _hip];
            m.DriftVec = new Vector3(m.DriftVec.X, 0, m.DriftVec.Z) * n / (n - 1);
            m.Drift = m.DriftVec.Length();
            m.DriftSpeed = m.Drift / m.Length;
            float lo = float.MaxValue, hi = float.MinValue;
            for (int k = 0; k < n; k++) { lo = Mathf.Min(lo, pos[k, _hip].Y); hi = Mathf.Max(hi, pos[k, _hip].Y); }
            m.HipBob = hi - lo;
        }

        // Per-sample step = the largest bone movement between consecutive samples; the wrap step is the loop seam.
        var steps = new float[n];
        for (int k = 0; k < n; k++)
        {
            int prev = (k + n - 1) % n;
            float mx = 0;
            for (int b = 0; b < bones; b++) mx = Mathf.Max(mx, pos[k, b].DistanceTo(pos[prev, b]));
            steps[k] = mx;
        }
        var sorted = steps.Skip(1).OrderBy(x => x).ToArray();
        m.MedianStep = sorted[sorted.Length / 2];
        m.SeamStep = steps[0];
        m.SeamRatio = m.SeamStep / Mathf.Max(m.MedianStep, 1e-5f);
        // Pose change relative to the hip (so a rigid slide of the whole body with frozen limbs still reads as a freeze),
        // and the body's speed over the ground: hip forward velocity plus the treadmill.
        var localSteps = new float[n];
        for (int k = 0; k < n; k++)
        {
            int prev = (k + n - 1) % n;
            for (int b = 0; b < bones; b++)
                localSteps[k] = Mathf.Max(localSteps[k], (pos[k, b] - pos[k, _hip >= 0 ? _hip : 0]).DistanceTo(pos[prev, b] - pos[prev, _hip >= 0 ? _hip : 0]));
        }
        m.LocalMedian = localSteps.OrderBy(x => x).ElementAt(n / 2);
        m.LocalSteps = localSteps;
        // Feet motion per sample (the largest foot/toe movement): a hitch shows up here even while arms keep moving.
        var feetSteps = new float[n];
        var footBones = _feet.SelectMany(f => new[] { f.foot, f.toe }).Where(b => b >= 0).ToArray();
        for (int k = 0; k < n; k++)
        {
            int prev = (k + n - 1) % n;
            foreach (int b in footBones) feetSteps[k] = Mathf.Max(feetSteps[k], pos[k, b].DistanceTo(pos[prev, b]));
        }
        var fsorted = feetSteps.OrderBy(x => x).ToArray();
        float feetMedian = fsorted[n / 2];
        m.Steps = footBones.Length > 0 ? feetSteps : steps;
        if (OS.GetEnvironment("ANIMLAB_DEBUG") != "")
        {
            var firsts = new SortedDictionary<double, int>();
            for (int t = 0; t < clip.GetTrackCount(); t++) if (clip.TrackGetKeyCount(t) > 0) { double ft = Math.Round(clip.TrackGetKeyTime(t, 0), 4); firsts[ft] = firsts.GetValueOrDefault(ft) + 1; }
            GD.Print($"DEBUG first-key times: {string.Join(", ", firsts.Select(kv => $"{kv.Key}s x{kv.Value}"))}; tracks {clip.GetTrackCount()}; feet median {feetMedian * 100:0.###} cm");
            var fwd = new Vector3(1, 0, 0);   // walk travels toward model +X
            foreach (int k in new[] { n - 8, n - 6, n - 4, n - 3, n - 2, n - 1, 0, 1, 2, 3, 4, 6, 8, 12 })
            {
                int pv = (k + n - 1) % n;
                string Sgn(int bone) => $"{(pos[k, bone] - pos[pv, bone]).Dot(fwd) * 100,6:0.00}";
                GD.Print($"DEBUG  k {k,4} t {k * dt:0.0000}  fwd step cm: hip {Sgn(_hip)}  L_foot {Sgn(_feet[0].foot)}  L_toe {Sgn(_feet[0].toe)}  R_foot {Sgn(_feet[1].foot)}  R_toe {Sgn(_feet[1].toe)}");
            }
        }
        m.StepsMedian = footBones.Length > 0 ? feetMedian : m.MedianStep;
        if (OS.GetEnvironment("ANIMLAB_DEBUG") != "")
        {
            GD.Print($"DEBUG {clipName} len {clip.Length} n {n} dt {dt:0.#####} median {m.MedianStep * 100:0.###} cm");
            foreach (int k in new[] { n - 6, n - 5, n - 4, n - 3, n - 2, n - 1, 0, 1, 2, 3, 4, 5, 6 })
            {
                int prev = (k + n - 1) % n, arg = 0; float mx = 0;
                for (int bb = 0; bb < bones; bb++) { float dd = pos[k, bb].DistanceTo(pos[prev, bb]); if (dd > mx) { mx = dd; arg = bb; } }
                GD.Print($"DEBUG  k {k,4} t {k * dt:0.0000}  step {steps[k] * 100:0.###} cm  worst {_skel.GetBoneName(arg)}");
            }
        }
        // Freeze: consecutive samples where the pose barely changes (e.g. a closing frame that repeats the first).
        {
            int best = 0, bestAt = -1;
            for (int k = 0; k < n; k++)
            {
                int run = 0;
                while (run < n && m.LocalSteps[(k + run) % n] < 0.2f * m.LocalMedian) run++;
                if (run > best) { best = run; bestAt = k; }
            }
            m.StallMs = best * dt * 1000f;
            if (bestAt >= 0) m.StallPhase = (float)bestAt / n;
        }
        for (int k = 1; k < n; k++)
            if (steps[k] > 4 * m.MedianStep && steps[k] > 0.02f)
                m.Spikes.Add($"t={k * dt:0.000}s step {steps[k] * 100:0.0} cm ({steps[k] / m.MedianStep:0.0}x median)");

        // Bone stretch: a rigid rig keeps parent-child distances constant (bones with translation keys move on purpose).
        var translated = new HashSet<string>();
        for (int t = 0; t < clip.GetTrackCount(); t++)
            if (clip.TrackGetType(t) == Animation.TrackType.Position3D) translated.Add(clip.TrackGetPath(t).GetConcatenatedSubNames());
        for (int b = 0; b < bones; b++)
        {
            int p = _skel.GetBoneParent(b);
            if (p < 0 || translated.Contains(_skel.GetBoneName(b))) continue;
            float lo = float.MaxValue, hi = 0;
            for (int k = 0; k < n; k++) { float d = pos[k, b].DistanceTo(pos[k, p]); lo = Mathf.Min(lo, d); hi = Mathf.Max(hi, d); }
            if (hi > 0.01f && (hi - lo) / hi > 0.02f) m.Stretch.Add($"{_skel.GetBoneName(b)} {(hi - lo) * 100:0.0} cm ({(hi - lo) / hi:P0})");
        }

        // Feet, in two passes. Pass 1: a foot is a contact candidate when it is near the floor (within PlantMargin
        // of its rest-pose sole height, or of its lowest point if the clip floats) and not rising or falling; the
        // median candidate velocity is the clip's ground velocity (in place: feet sweep backward; root motion: ~0).
        // Pass 2: planted = candidate AND moving with the ground — a swinging foot can skim the floor, but it moves
        // fast relative to the ground. Blips shorter than 5% of the clip are dropped, and lifts under 3% merged.
        var planted = new bool[_feet.Count, n];
        var candidate = new bool[_feet.Count, n];
        var vels = new List<Vector3>();
        Vector3 Vel(int f, int k) { var v = (footP[f, (k + 1) % n] - footP[f, (k + n - 1) % n]) / (2 * dt); return new Vector3(v.X, 0, v.Z); }
        for (int f = 0; f < _feet.Count; f++)
        {
            float min = float.MaxValue;
            for (int k = 0; k < n; k++) min = Mathf.Min(min, footH[f, k]);
            m.FootAbsMin[_feet[f].name] = min;
            m.FootMin[_feet[f].name] = min - _footRest.GetValueOrDefault(_feet[f].name);   // relative to the rest-pose sole
            float floor = Mathf.Max(_footRest.GetValueOrDefault(_feet[f].name), min);
            for (int k = 0; k < n; k++)
            {
                float vy = (footH[f, (k + 1) % n] - footH[f, (k + n - 1) % n]) / (2 * dt);
                candidate[f, k] = footH[f, k] < floor + PlantMargin && Mathf.Abs(vy) < 0.25f;
                if (candidate[f, k]) vels.Add(Vel(f, k));
            }
        }
        if (vels.Count > 0)
        {
            var xs = vels.Select(v => v.X).OrderBy(x => x).ToList();
            var zs = vels.Select(v => v.Z).OrderBy(x => x).ToList();
            m.GroundVel = new Vector3(xs[xs.Count / 2], 0, zs[zs.Count / 2]);
        }
        float withGround = Mathf.Max(0.25f, m.GroundVel.Length() * 0.5f);
        int minPlant = Mathf.Max(2, (int)(n * 0.05f)), gap = Mathf.Max(1, (int)(n * 0.03f));
        for (int f = 0; f < _feet.Count; f++)
        {
            for (int k = 0; k < n; k++) planted[f, k] = candidate[f, k] && (Vel(f, k) - m.GroundVel).Length() < withGround;
            // merge short lifts
            for (int k = 0; k < n; k++)
            {
                if (planted[f, k] || !planted[f, (k + n - 1) % n]) continue;
                int e2 = 0;
                while (e2 < gap && !planted[f, (k + e2) % n]) e2++;
                if (e2 < gap) for (int j = 0; j < e2; j++) planted[f, (k + j) % n] = true;
            }
            // drop blips
            for (int k = 0; k < n; k++)
            {
                if (!planted[f, k] || planted[f, (k + n - 1) % n]) continue;
                int len = 0;
                while (len < n && planted[f, (k + len) % n]) len++;
                if (len < minPlant) for (int j = 0; j < len; j++) planted[f, (k + j) % n] = false;
            }
            int count = 0;
            for (int k = 0; k < n; k++) { m.Plant[_feet[f].name][k] = planted[f, k]; if (planted[f, k]) count++; }
            m.FootPlanted[_feet[f].name] = (float)count / n;
        }
        // Travel direction in the character's frame: feet push the ground backward, root motion carries it forward.
        var travel = -m.GroundVel + m.DriftVec / m.Length;
        m.GroundSpeed = travel.Length();
        if (m.GroundSpeed > 0.1f)
        {
            var d = travel.Normalized();
            m.Travel = Mathf.Abs(d.Z) >= Mathf.Abs(d.X) ? (d.Z > 0 ? "toward model +Z" : "toward model -Z") : (d.X > 0 ? "toward model +X" : "toward model -X");
            m.TravelYaw = Mathf.RadToDeg(Mathf.Atan2(d.X, d.Z));
        }

        // Body speed over the ground along the travel direction: treadmill speed + the hip's own forward motion.
        if (_hip >= 0 && m.GroundSpeed > 0.1f)
        {
            var dir = travel.Normalized();
            m.BodySpeed = new float[n];
            m.BodyMin = float.MaxValue;
            for (int k = 0; k < n; k++)
            {
                int prev = (k + n - 1) % n;
                m.BodySpeed[k] = (pos[k, _hip] - pos[prev, _hip]).Dot(dir) / dt - m.GroundVel.Dot(dir);
                if (m.BodySpeed[k] < m.BodyMin) { m.BodyMin = m.BodySpeed[k]; m.BodyMinPhase = (float)k / n; }
            }
        }

        // Side-to-side: hip sway and sideways slide of planted feet, across the travel direction.
        // Side axis: across this clip's travel, or — for a clip that stays put (idle) — across the travel of a
        // moving clip analyzed earlier in the run, so idle sway is measured left/right of the character too.
        var facing = m.GroundSpeed > 0.1f ? travel : _results.FirstOrDefault(r => r.GroundSpeed > 0.1f)?.TravelVec ?? Vector3.Back;
        m.TravelVec = travel;
        var side = new Vector3(facing.Z, 0, -facing.X).Normalized();
        if (_hip >= 0)
        {
            float lo = float.MaxValue, hi = float.MinValue;
            for (int k = 0; k < n; k++) { float x = pos[k, _hip].Dot(side); lo = Mathf.Min(lo, x); hi = Mathf.Max(hi, x); }
            m.Sway = hi - lo;
        }

        // Plants per foot as (start, length) in samples, wrapping around the loop. Slide = the farthest a planted
        // foot strays from where it landed, after removing the treadmill's motion (so jitter doesn't accumulate).
        var centers = new float[_feet.Count];
        for (int f = 0; f < _feet.Count; f++)
        {
            int k0 = 0;
            while (k0 < n && planted[f, k0]) k0++;          // begin the scan at a lifted sample so plants don't split at the wrap
            var slides = new List<float>();
            int bestLen = 0; float bestCenter = 0;
            int j = 0;
            while (j < n)
            {
                int k = (k0 + j) % n;
                if (!planted[f, k]) { j++; continue; }
                int s0 = j;
                var land = footP[f, k];
                float worst = 0;
                while (j < n && planted[f, (k0 + j) % n])
                {
                    var p = footP[f, (k0 + j) % n];
                    var off = (p - land) - m.GroundVel * ((j - s0) * dt);
                    off.Y = 0;
                    worst = Mathf.Max(worst, off.Length());
                    m.LateralSlideMax = Mathf.Max(m.LateralSlideMax, Mathf.Abs(off.Dot(side)));
                    j++;
                }
                slides.Add(worst);
                {
                    float heelMin = float.MaxValue, toeMin = float.MaxValue;
                    for (int q = s0; q < j; q++) { int kk = (k0 + q) % n; heelMin = Mathf.Min(heelMin, m.Heel[_feet[f].name][kk]); toeMin = Mathf.Min(toeMin, m.Toe[_feet[f].name][kk]); }
                    m.PlantHeels.Add((_feet[f].name, heelMin * 100));
                    m.Plants.Add($"{_feet[f].name} plant {(float)((k0 + s0) % n) / n:0.00}-{(float)((k0 + j) % n) / n:0.00}: heel low {heelMin * 100:+0.0;-0.0} cm, toe low {toeMin * 100:+0.0;-0.0} cm, slide {worst * 100:0.0} cm");
                }
                if (j - s0 > bestLen) { bestLen = j - s0; bestCenter = ((k0 + s0 + (j - s0) / 2f) % n) / n; }
            }
            centers[f] = bestCenter;
            if (f == 0) m.Strides = Mathf.Max(1, slides.Count);
            m.SlideMax[_feet[f].name] = slides.Count > 0 ? slides.Max() : 0;
            m.SlideMean[_feet[f].name] = slides.Count > 0 ? slides.Average() : 0;
        }
        if (_feet.Count == 2 && m.GroundSpeed > 0.1f)
            m.PhaseOffset = Mathf.PosMod((centers[1] - centers[0]) * m.Strides, 1f);   // in strides: 0.5 = even gait

        Judge(m);
        _anim.Stop();
        return m;
    }

    static void Judge(Metrics m)
    {
        void Add(string lvl, string t) => m.Findings.Add((lvl, t));
        bool moving = m.GroundSpeed > 0.1f;
        if (m.MedianStep < 1e-6f && m.SeamStep < 1e-6f)
        {
            Add("FAIL", "no bone moved while sampling — the clip is empty or the skeleton wasn't posed (analysis is invalid)");
            return;
        }
        if (m.Drift > 0.05f)
            Add(m.SeamRatio > 4 ? "FAIL" : "WARN", $"root drift {m.Drift:0.00} m per cycle ({m.DriftSpeed:0.00} m/s) — loops snap the body back unless stripped (--strip-root) or used as root motion");
        if (m.BodySpeed != null && m.BodyMin < 0.25f * m.GroundSpeed)
            Add(m.BodyMin < 0 ? "FAIL" : "WARN", $"body {(m.BodyMin < 0 ? "moves backward" : "nearly stops")} over the ground at phase {m.BodyMinPhase:0.00} ({m.BodyMin:0.00} m/s vs {m.GroundSpeed:0.00} average) — a visible hitch{(m.BodyMinPhase < 0.03f || m.BodyMinPhase > 0.97f ? " at the loop (duplicated first key? try --fix-loop)" : "")}");
        if (m.StallMs >= 15f && moving)
            Add(m.StallMs >= 25f ? "FAIL" : "WARN", $"pose freezes for {m.StallMs:0} ms at phase {m.StallPhase:0.00} — a hitch; while the body keeps moving, feet slip{(m.StallPhase < 0.03f || m.StallPhase > 0.97f ? " (at the loop: duplicated first key? try --fix-loop)" : "")}");
        if (m.SeamRatio > 4 && m.SeamStep > 0.02f) Add("FAIL", $"loop seam pop: {m.SeamStep * 100:0.0} cm at wrap ({m.SeamRatio:0.0}x a normal frame)");
        else if (m.SeamRatio > 2 && m.SeamStep > 0.01f) Add("WARN", $"loop seam hitch: {m.SeamStep * 100:0.0} cm at wrap ({m.SeamRatio:0.0}x)");
        if (m.Spikes.Count > 0) Add("FAIL", $"{m.Spikes.Count} single-frame bone jump(s), first {m.Spikes[0]}");
        if (m.Stretch.Count > 0) Add("WARN", $"{m.Stretch.Count} bone(s) change length: {string.Join("; ", m.Stretch.Take(3))}");
        foreach (var (foot, min) in m.FootMin)
        {
            if (min < -0.02f) Add("WARN", $"{foot} foot sinks {-min * 100:0.0} cm below the floor");
            if (min > 0.04f && moving) Add("WARN", $"{foot} foot never touches the floor (lowest {min * 100:0.0} cm)");
        }
        if (moving)
        {
            if (Mathf.Abs(m.TravelYaw) > 20f)
                Add("WARN", $"clip travels {m.Travel} (heading {m.TravelYaw:0}° from +Z): a game that faces +Z along the path must yaw this model by {-m.TravelYaw:0}° — or it walks sideways/backward");
            foreach (var (foot, s) in m.SlideMax)
                if (s > 0.08f) Add("FAIL", $"{foot} foot slides {s * 100:0.0} cm during a plant");
                else if (s > 0.03f) Add("WARN", $"{foot} foot slides {s * 100:0.0} cm during a plant");
            if (m.PhaseOffset >= 0 && Mathf.Abs(m.PhaseOffset - 0.5f) > 0.12f) Add("WARN", $"left/right plants offset {m.PhaseOffset:0.00} of a cycle (0.50 is an even gait) — limp");
            if (m.Strides > 1)
            {
                foreach (var foot in m.Heel.Keys)
                {
                    var lows = m.PlantHeels.Where(p => p.foot == foot).Select(p => p.heelLow).ToList();
                    if (lows.Count > 1 && lows.Max() - lows.Min() > 1.0f)
                        Add("WARN", $"{foot} steps differ: heel lands {lows.Min():+0.0;-0.0} to {lows.Max():+0.0;-0.0} cm vs rest across the clip's {m.Strides} strides — inconsistent contacts");
                }
            }
        }
        foreach (var foot in m.Heel.Keys)
        {
            foreach (var (part, series) in new[] { ("heel", m.Heel[foot]), ("toe", m.Toe[foot]) })
            {
                int at = 0;
                for (int k = 1; k < series.Length; k++) if (series[k] < series[at]) at = k;
                if (series[at] < -0.015f)
                    Add("WARN", $"{foot} {part} dips {-series[at] * 100:0.0} cm below its rest height at phase {(float)at / series.Length:0.00} — sinks into the floor");
            }
        }
        if (moving && m.Sway > 0.08f) Add("WARN", $"hip sways {m.Sway * 100:0} cm side to side per cycle (a natural walk is ~4–6 cm) — the body rocks left/right");
        if (m.LateralSlideMax > 0.03f) Add("WARN", $"planted feet slide up to {m.LateralSlideMax * 100:0.0} cm sideways");
        if (m.Findings.Count == 0) Add("PASS", "no issues found");
    }

    void WriteReport()
    {
        var sb = new StringBuilder("{\n  \"model\": \"" + _o.Model + "\",\n  \"strip_root\": " + (_o.StripRoot ? "true" : "false") + ",\n  \"clips\": [\n");
        for (int i = 0; i < _results.Count; i++)
        {
            var m = _results[i];
            string Dict(Dictionary<string, float> d) => "{" + string.Join(", ", d.Select(kv => $"\"{kv.Key}\": {kv.Value:0.####}")) + "}";
            string Arr(IEnumerable<string> a) => "[" + string.Join(", ", a.Select(x => "\"" + x.Replace("\"", "'") + "\"")) + "]";
            sb.Append($"    {{\"clip\": \"{m.Clip}\", \"length_s\": {m.Length:0.###}, \"ground_speed_mps\": {m.GroundSpeed:0.###}, \"travel\": \"{m.Travel}\", ")
              .Append($"\"root_drift_m\": {m.Drift:0.###}, \"seam_step_cm\": {m.SeamStep * 100:0.##}, \"seam_ratio\": {m.SeamRatio:0.##}, \"freeze_ms\": {m.StallMs:0},  \"median_step_cm\": {m.MedianStep * 100:0.###}, ")
.Append($"\"hip_bob_cm\": {m.HipBob * 100:0.#}, \"hip_sway_cm\": {m.Sway * 100:0.#}, \"lateral_slide_max_cm\": {m.LateralSlideMax * 100:0.#}, \"phase_offset\": {m.PhaseOffset:0.###}, \"foot_min_m\": {Dict(m.FootMin)}, \"planted_fraction\": {Dict(m.FootPlanted)}, ")
              .Append($"\"slide_max_m\": {Dict(m.SlideMax)}, \"slide_mean_m\": {Dict(m.SlideMean)}, \"plants\": {Arr(m.Plants)}, \"spikes\": {Arr(m.Spikes)}, \"stretch\": {Arr(m.Stretch)}, ")
              .Append($"\"findings\": {Arr(m.Findings.Select(f => f.level + ": " + f.text))}}}")
              .Append(i < _results.Count - 1 ? ",\n" : "\n");

            GD.Print($"AnimLab [{m.Clip}] {m.Length:0.##}s  speed {m.GroundSpeed:0.00} m/s {m.Travel}  drift {m.Drift:0.00} m  seam {m.SeamRatio:0.0}x  freeze {m.StallMs:0} ms  body-min {(m.BodySpeed != null ? m.BodyMin : 0):0.00} m/s  bob {m.HipBob * 100:0.0} cm  sway {m.Sway * 100:0.0} cm  side-slide {m.LateralSlideMax * 100:0.0} cm  " +
                     string.Join("  ", m.SlideMax.Select(kv => $"slide {kv.Key} {kv.Value * 100:0.0} cm")));
            foreach (var pl in m.Plants) GD.Print($"AnimLab [{m.Clip}]   {pl}");
            foreach (var (lvl, text) in m.Findings)
                if (lvl == "FAIL") GD.PushError($"AnimLab [{m.Clip}] {text}");
                else GD.Print($"AnimLab [{m.Clip}] {lvl}: {text}");
        }
        sb.Append("  ]\n}\n");
        var path = ProjectSettings.GlobalizePath(_o.Report);
        System.IO.Directory.CreateDirectory(System.IO.Path.GetDirectoryName(path));
        System.IO.File.WriteAllText(path, sb.ToString());
        GD.Print($"AnimLab report {path}  (playback {_results.Sum(ShowTime):0.#} s)");
    }

    // ---------------------------------------------------------------- playback

    void NextClip()
    {
        _clipIndex++;
        if (_clipIndex >= _results.Count)
        {
            if (!_o.Loop) { Quit(0); return; }
            _clipIndex = 0;
        }
        _cur = _results[_clipIndex];
        _clipTime = 0;
        _anim.Play(_cur.Clip);
        _anim.Seek(0, true);
        foreach (var t in _trails.Values) t.Clear();
        foreach (Node c in _ground.GetChildren()) if (c != _trailMesh) c.QueueFree();
        _wasPlanted.Clear();
        _lastPrint.Clear();
    }

    string _dll;
    DateTime _dllTime;
    double _watch;

    // Interactive (--loop) sessions restart themselves when the project is rebuilt, so the window always runs the
    // latest AnimLab code with the same arguments.
    void WatchForRebuild(double delta)
    {
        if (!_o.Loop) return;
        _dll ??= System.IO.Path.Combine(ProjectSettings.GlobalizePath("res://.godot/mono/temp/bin/Debug"), ProjectSettings.GetSetting("dotnet/project/assembly_name").AsString() + ".dll");
        if (_dllTime == default) { _dllTime = System.IO.File.GetLastWriteTime(_dll); return; }
        _watch += delta;
        if (_watch < 1.0) return;
        _watch = 0;
        var now = System.IO.File.GetLastWriteTime(_dll);
        if (now == _dllTime || (DateTime.Now - now).TotalSeconds < 1.5) return;   // let the build finish writing
        var args = new List<string>(OS.GetCmdlineArgs()) { "++" };
        args.AddRange(OS.GetCmdlineUserArgs());
        GD.Print("AnimLab: rebuilt — restarting");
        OS.CreateProcess(OS.GetExecutablePath(), args.ToArray());
        Quit(0);
    }

    public override bool _Process(double delta)
    {
        if (_o == null) return false;
        WatchForRebuild(delta);
        if (_results.Count == 0) { AnalyzeAll(); return false; }
        if (_cur == null) return false;
        _clipTime += delta;
        if (_clipTime >= ShowTime(_cur)) { NextClip(); return false; }

        // Treadmill: the ground carries planted feet at the clip's measured ground velocity.
        _ground.Position += _cur.GroundVel * (float)delta;
        _gridMat.SetShaderParameter("offset", new Vector2(_ground.Position.X, _ground.Position.Z));

        foreach (var (name, foot, toe) in _feet)
        {
            var p = FootPoint(foot, toe);
            // Same plants the analysis found, looked up at the current phase, so the view matches the report.
            var plan = _cur.Plant[name];
            bool planted = plan[(int)(_clipTime % _cur.Length / _cur.Length * plan.Length) % plan.Length];
            var local = p - _ground.Position;
            Trail(name, local);
            _wasPlanted.TryGetValue(name, out bool was);
            if (planted && !was)
            {
                var mark = new MeshInstance3D
                {
                    Mesh = new BoxMesh { Size = new Vector3(0.1f, 0.004f, 0.16f) },
                    Position = new Vector3(local.X, 0.003f, local.Z),
                    CastShadow = GeometryInstance3D.ShadowCastingSetting.Off,
                };
                _ground.AddChild(mark);
                _lastPrint[name] = (mark, local);
            }
            if (planted && _lastPrint.TryGetValue(name, out var lp))
            {
                // Colour the footprint by how far the foot has slid off it: green holds, red slides.
                float off = new Vector2(local.X - lp.at.X, local.Z - lp.at.Z).Length();
                var col = new Color(0.3f, 0.85f, 0.4f).Lerp(new Color(0.95f, 0.25f, 0.2f), Mathf.Clamp(off / 0.08f, 0, 1));
                ((MeshInstance3D)lp.mark).MaterialOverride = new StandardMaterial3D { AlbedoColor = col, ShadingMode = BaseMaterial3D.ShadingModeEnum.Unshaded };
            }
            _wasPlanted[name] = planted;
        }
        if (_hip >= 0) Trail("hip", BoneWorld(_hip) - _ground.Position);
        DrawTrails();
        DrawBones();
        DrawHud();
        _graph.QueueRedraw();
        return false;
    }

    // Heel (solid) and toe (thin) height per foot over one cycle, planted stretches shaded, playhead at the
    // current phase. 0 is the rest-pose height: below the dashed line the foot is sinking into the floor.
    void DrawGraph()
    {
        if (_cur == null || _cur.Heel.Count == 0) return;
        var g = _graph;
        var size = g.Size;
        const float lo = -0.04f, hi = 0.14f;
        var full = size;
        size = new Vector2(size.X, full.Y * 0.62f);
        float Y(float h) => size.Y * (1f - (Mathf.Clamp(h, lo, hi) - lo) / (hi - lo));
        g.DrawRect(new Rect2(Vector2.Zero, full), new Color(0.12f, 0.125f, 0.15f));
        var colors = new Dictionary<string, Color> { ["L"] = new(0.35f, 0.6f, 1f), ["R"] = new(1f, 0.6f, 0.25f) };
        int row = 0;
        foreach (var (foot, plant) in _cur.Plant)
        {
            var c = colors.GetValueOrDefault(foot, Colors.White);
            float y0 = size.Y - 10 - row * 10;
            for (int k = 0; k < plant.Length; k++)
                if (plant[k]) g.DrawRect(new Rect2(size.X * k / plant.Length, y0, size.X / plant.Length + 1, 7), new Color(c, 0.55f));
            row++;
        }
        for (float x = 0; x < size.X; x += 12) g.DrawLine(new Vector2(x, Y(0)), new Vector2(x + 6, Y(0)), new Color(1, 1, 1, 0.5f), 1);
        g.DrawString(ThemeDB.FallbackFont, new Vector2(4, Y(0) - 4), "rest / floor", HorizontalAlignment.Left, -1, 14, new Color(1, 1, 1, 0.5f));
        g.DrawString(ThemeDB.FallbackFont, new Vector2(4, 16), "foot height · heel ━  toe ─ · planted ▬", HorizontalAlignment.Left, -1, 15, new Color(1, 1, 1, 0.7f));
        foreach (var foot in _cur.Heel.Keys)
        {
            var c = colors.GetValueOrDefault(foot, Colors.White);
            foreach (var (series, w) in new[] { (_cur.Heel[foot], 2.5f), (_cur.Toe[foot], 1f) })
            {
                var pts = new Vector2[series.Length];
                for (int k = 0; k < series.Length; k++) pts[k] = new Vector2(size.X * k / (series.Length - 1), Y(series[k]));
                g.DrawPolyline(pts, c, w, true);
            }
        }
        // Body speed over the ground (hip forward speed + treadmill): dips mean a stall, below zero it slides back.
        if (_cur.BodySpeed != null)
        {
            var bs = _cur.BodySpeed;
            float top = size.Y + 8, h = full.Y - top - 2, avg = _cur.GroundSpeed, cap = avg * 2f;
            g.DrawString(ThemeDB.FallbackFont, new Vector2(4, top + 14), $"body speed over ground (dashed = {avg:0.00} m/s average, solid = 0; red = stall / backward)", HorizontalAlignment.Left, -1, 14, new Color(1, 1, 1, 0.7f));
            float YS(float v) => top + h * (1f - Mathf.Clamp((v + avg * 0.5f) / (cap + avg * 0.5f), 0, 1));
            g.DrawLine(new Vector2(0, YS(0)), new Vector2(size.X, YS(0)), new Color(1, 1, 1, 0.5f), 1);
            for (float x = 0; x < size.X; x += 12) g.DrawLine(new Vector2(x, YS(avg)), new Vector2(x + 6, YS(avg)), new Color(1, 1, 1, 0.35f), 1);
            for (int k = 1; k < bs.Length; k++)
            {
                bool bad = bs[k] < 0.25f * avg;
                var col = bad ? new Color(1f, 0.3f, 0.25f) : new Color(0.55f, 0.95f, 0.6f);
                g.DrawLine(new Vector2(size.X * (k - 1) / bs.Length, YS(bs[k - 1])), new Vector2(size.X * k / bs.Length, YS(bs[k])), col, bad ? 3f : 1.5f);
            }
            bool wrapBad = bs[0] < 0.25f * avg;
            g.DrawCircle(new Vector2(4, YS(bs[0])), 4, wrapBad ? new Color(1f, 0.3f, 0.25f) : new Color(0.55f, 0.95f, 0.6f));
        }
        float phase = (float)(_clipTime % _cur.Length / _cur.Length);
        g.DrawLine(new Vector2(size.X * phase, 0), new Vector2(size.X * phase, full.Y), new Color(1, 1, 1, 0.8f), 1.5f);
    }

    // Short cycles repeat; a long clip (idles often run 10 s+) plays once.
    double ShowTime(Metrics m) => m.Length * (m.Length > 6f ? 1 : _o.Cycles);

    void Trail(string key, Vector3 p)
    {
        if (!_trails.TryGetValue(key, out var list)) _trails[key] = list = new List<Vector3>();
        list.Add(p);
        if (list.Count > 150) list.RemoveAt(0);
    }

    void DrawTrails()
    {
        var im = (ImmediateMesh)_trailMesh.Mesh;
        im.ClearSurfaces();
        var colors = new Dictionary<string, Color> { ["L"] = new(0.35f, 0.6f, 1f), ["R"] = new(1f, 0.6f, 0.25f), ["hip"] = new(1f, 0.9f, 0.3f) };
        foreach (var (key, pts) in _trails)
        {
            if (pts.Count < 2) continue;
            im.SurfaceBegin(Mesh.PrimitiveType.LineStrip, _lineMat);
            for (int i = 0; i < pts.Count; i++)
            {
                var c = colors.GetValueOrDefault(key, Colors.White);
                im.SurfaceSetColor(new Color(c, (float)i / pts.Count));
                im.SurfaceAddVertex(pts[i]);
            }
            im.SurfaceEnd();
        }
    }

    void DrawBones()
    {
        var im = (ImmediateMesh)_bonesMesh.Mesh;
        im.ClearSurfaces();
        im.SurfaceBegin(Mesh.PrimitiveType.Lines, _lineMat);
        for (int b = 0; b < _skel.GetBoneCount(); b++)
        {
            int p = _skel.GetBoneParent(b);
            if (p < 0) continue;
            im.SurfaceSetColor(new Color(0.4f, 1f, 1f, 0.7f));
            im.SurfaceAddVertex(BoneWorld(p));
            im.SurfaceSetColor(new Color(0.4f, 1f, 1f, 0.7f));
            im.SurfaceAddVertex(BoneWorld(b));
        }
        im.SurfaceEnd();
    }

    void DrawHud()
    {
        var m = _cur;
        float phase = (float)(_clipTime % m.Length / m.Length);
        int bar = 30;
        var sb = new StringBuilder();
        sb.AppendLine($"{m.Clip}   {m.Length:0.00}s   cycle {(int)(_clipTime / m.Length) + 1}/{(int)Math.Round(ShowTime(m) / m.Length)}   {(_o.StripRoot ? "root stripped" : "raw")}");
        sb.AppendLine("[" + new string('#', (int)(phase * bar)) + new string('.', bar - (int)(phase * bar)) + $"] {phase:0.00}");
        sb.AppendLine($"speed {m.GroundSpeed:0.00} m/s {m.Travel}    drift {m.Drift:0.00} m    seam {m.SeamRatio:0.0}x    freeze {m.StallMs:0} ms    body min {(m.BodySpeed != null ? m.BodyMin : 0):0.00} m/s    bob {m.HipBob * 100:0.0} cm    sway {m.Sway * 100:0.0} cm");
        foreach (var f in m.SlideMax.Keys)
            sb.Append($"{f}: planted {m.FootPlanted[f]:P0}  slide {m.SlideMax[f] * 100:0.0} cm  sole {m.FootMin[f] * 100:+0.0;-0.0} cm      ");
        sb.AppendLine();
        if (m.PhaseOffset >= 0) sb.AppendLine($"strides/clip {m.Strides}   L/R phase {m.PhaseOffset:0.00} (0.50 = even)");
        foreach (var (lvl, text) in m.Findings) sb.AppendLine($"{lvl}: {(text.Length > 90 ? text[..90] + "…" : text)}");
        _hud.Text = sb.ToString();
        _title.Text = $"{m.Clip}   ·   {System.IO.Path.GetFileNameWithoutExtension(_o.Model)}   ·   {(_o.StripLocal ? "root stripped (naive)" : _o.StripRoot ? "root stripped" : "raw clip")}{(_o.FixLoop ? " + loop fixed" : "")}{(_o.GameForward != null ? $"   ·   game forward {_o.GameForward}" : "")}";
        if (_dllTime != default) _title.Text += $"      build {_dllTime:HH:mm:ss}";
    }

    // ---------------------------------------------------------------- helpers

    // Removes the Hip's linear drift over the clip (keeps sway and bob). The drift is measured and removed in
    // the parent bone's frame *after* that bone's own animated rotation: the Tripo rig wobbles its Root a few
    // degrees, and removing drift in Hip-local space leaves the wobble acting on a vanished 1.6 m lever — a
    // fake 19 cm side-to-side sway with sliding feet.
    static Vector3 StripRootMotion(Animation clip, Skeleton3D skel)
    {
        for (int t = 0; t < clip.GetTrackCount(); t++)
        {
            if (clip.TrackGetType(t) != Animation.TrackType.Position3D) continue;
            string bone = clip.TrackGetPath(t).GetConcatenatedSubNames();
            var lower = bone.ToLowerInvariant();
            if (lower != "hip" && lower != "hips" && lower != "pelvis") continue;
            int n = clip.TrackGetKeyCount(t);
            if (n < 2) return Vector3.Zero;

            int b = skel.FindBone(bone), parent = b >= 0 ? skel.GetBoneParent(b) : -1;
            int rotTrack = -1;
            if (parent >= 0)
            {
                string pname = skel.GetBoneName(parent);
                for (int r = 0; r < clip.GetTrackCount(); r++)
                    if (clip.TrackGetType(r) == Animation.TrackType.Rotation3D && clip.TrackGetPath(r).GetConcatenatedSubNames() == pname) rotTrack = r;
            }
            var rest = parent >= 0 ? skel.GetBoneRest(parent).Basis.GetRotationQuaternion() : Quaternion.Identity;
            Quaternion Rot(double time) => (rotTrack >= 0 ? clip.RotationTrackInterpolate(rotTrack, time) : rest).Normalized();

            double t0 = clip.TrackGetKeyTime(t, 0), t1 = clip.TrackGetKeyTime(t, n - 1);
            var p0 = Rot(t0) * (Vector3)clip.TrackGetKeyValue(t, 0);
            var drift = Rot(t1) * (Vector3)clip.TrackGetKeyValue(t, n - 1) - p0;
            for (int k = 0; k < n; k++)
            {
                double time = clip.TrackGetKeyTime(t, k);
                var q = Rot(time);
                var p = q * (Vector3)clip.TrackGetKeyValue(t, k) - drift * (float)((time - t0) / (t1 - t0));
                clip.TrackSetKeyValue(t, k, q.Inverse() * p);
            }
            return drift;
        }
        return Vector3.Zero;
    }

    // Tripo's glTF keys start at 1/30 s; Godot's importer adds a key at t=0 that copies the first pose. Played as a
    // loop, that pose is held for a frame (legs freeze) — and a root-drift strip turns the copy into a 2 cm backward
    // step of the whole body. Remove the copied key and shift the clip to start at the real first key; the closing
    // key (a repeat of the first pose) then lands exactly on the loop point.
    static bool NormalizeLoop(Animation clip)
    {
        double shift = -1;
        for (int t = 0; t < clip.GetTrackCount(); t++)
        {
            if (clip.TrackGetKeyCount(t) < 3 || clip.TrackGetKeyTime(t, 0) > 1e-4) continue;
            var a = clip.TrackGetKeyValue(t, 0);
            var b = clip.TrackGetKeyValue(t, 1);
            bool same = clip.TrackGetType(t) switch
            {
                Animation.TrackType.Rotation3D => Mathf.Abs(((Quaternion)a).Dot((Quaternion)b)) > 0.999999f,
                Animation.TrackType.Position3D or Animation.TrackType.Scale3D => ((Vector3)a).DistanceTo((Vector3)b) < 1e-6f,
                _ => false,
            };
            if (!same) return false;   // a real first frame at t=0: nothing to fix
            shift = clip.TrackGetKeyTime(t, 1);
        }
        if (shift <= 0) return false;
        for (int t = 0; t < clip.GetTrackCount(); t++)
        {
            if (clip.TrackGetKeyCount(t) >= 2 && clip.TrackGetKeyTime(t, 0) < 1e-4 && clip.TrackGetKeyTime(t, 1) <= shift + 1e-4) clip.TrackRemoveKey(t, 0);
            for (int k = 0; k < clip.TrackGetKeyCount(t); k++)
                clip.TrackSetKeyTime(t, k, Math.Max(0, clip.TrackGetKeyTime(t, k) - shift));
        }
        clip.Length = (float)(clip.Length - shift);
        return true;
    }

    // The naive strip: removes the Hip's drift in its own track space. Kept only to show what it gets wrong.
    static void StripRootMotionLocal(Animation clip)
    {
        for (int t = 0; t < clip.GetTrackCount(); t++)
        {
            if (clip.TrackGetType(t) != Animation.TrackType.Position3D) continue;
            var lower = clip.TrackGetPath(t).GetConcatenatedSubNames().ToLowerInvariant();
            if (lower != "hip" && lower != "hips" && lower != "pelvis") continue;
            int n = clip.TrackGetKeyCount(t);
            if (n < 2) return;
            var drift = (Vector3)clip.TrackGetKeyValue(t, n - 1) - (Vector3)clip.TrackGetKeyValue(t, 0);
            double t0 = clip.TrackGetKeyTime(t, 0), t1 = clip.TrackGetKeyTime(t, n - 1);
            for (int k = 0; k < n; k++)
                clip.TrackSetKeyValue(t, k, (Vector3)clip.TrackGetKeyValue(t, k) - drift * (float)((clip.TrackGetKeyTime(t, k) - t0) / (t1 - t0)));
            return;
        }
    }

    static T Find<T>(Node n) where T : Node
    {
        if (n is T t) return t;
        foreach (var c in n.GetChildren()) if (Find<T>(c) is { } f) return f;
        return null;
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
        foreach (var c in n.GetChildren()) MergeBounds(c, xf, ref box, ref any);
    }

    const string GridShader = @"
shader_type spatial;
render_mode unshaded;
uniform vec2 offset;
varying vec3 wp;
void vertex() { wp = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz; }
float grid(vec2 p, float step, float w) {
    vec2 d = abs(fract(p / step - 0.5) - 0.5) * step;
    vec2 aa = fwidth(p) * 1.5;
    vec2 l = 1.0 - smoothstep(vec2(w), vec2(w) + aa, d);
    return max(l.x, l.y);
}
void fragment() {
    vec2 p = wp.xz - offset;
    float minor = grid(p, 0.25, 0.004);
    float major = grid(p, 1.0, 0.012);
    float fade = 1.0 - smoothstep(4.0, 12.0, length(wp.xz));
    ALBEDO = mix(vec3(0.22, 0.23, 0.26), vec3(0.75, 0.78, 0.85), max(minor * 0.35, major) * fade);
}";
}

// Minimal GLB surgery: replace the images of an exported GLB with the source GLB's original image bytes, matched by
// material and role (base color, metallic-roughness, normal, occlusion, emissive), then repack the binary chunk.
static class GlbTextures
{
    static (System.Text.Json.Nodes.JsonObject json, byte[] bin) Read(string path)
    {
        var d = System.IO.File.ReadAllBytes(path);
        int jsonLen = BitConverter.ToInt32(d, 12);
        var json = System.Text.Json.Nodes.JsonNode.Parse(System.Text.Encoding.UTF8.GetString(d, 20, jsonLen)).AsObject();
        int binStart = 20 + jsonLen;
        byte[] bin = Array.Empty<byte>();
        if (binStart + 8 <= d.Length)
        {
            int binLen = BitConverter.ToInt32(d, binStart);
            bin = new byte[binLen];
            Array.Copy(d, binStart + 8, bin, 0, binLen);
        }
        return (json, bin);
    }

    static Dictionary<string, int> ImagesByRole(System.Text.Json.Nodes.JsonObject j)
    {
        var map = new Dictionary<string, int>();
        var mats = j["materials"]?.AsArray();
        var texs = j["textures"]?.AsArray();
        if (mats == null || texs == null) return map;
        for (int m = 0; m < mats.Count; m++)
        {
            var mat = mats[m].AsObject();
            var pbr = mat["pbrMetallicRoughness"]?.AsObject();
            var roles = new (string role, System.Text.Json.Nodes.JsonNode node)[]
            {
                ("baseColor", pbr?["baseColorTexture"]), ("metallicRoughness", pbr?["metallicRoughnessTexture"]),
                ("normal", mat["normalTexture"]), ("occlusion", mat["occlusionTexture"]), ("emissive", mat["emissiveTexture"]),
            };
            string key = mat["name"]?.GetValue<string>() ?? $"#{m}";
            foreach (var (role, node) in roles)
                if (node?["index"] is { } ti && texs[ti.GetValue<int>()]?["source"] is { } src)
                    map[$"{key}/{role}"] = src.GetValue<int>();
        }
        return map;
    }

    static byte[] Slice(System.Text.Json.Nodes.JsonObject j, byte[] bin, int bufferView)
    {
        var bv = j["bufferViews"][bufferView];
        int off = bv["byteOffset"]?.GetValue<int>() ?? 0, len = bv["byteLength"].GetValue<int>();
        return bin.AsSpan(off, len).ToArray();
    }

    public static int CopyFrom(string sourceGlb, string exportedGlb)
    {
        var (src, srcBin) = Read(sourceGlb);
        var (dst, dstBin) = Read(exportedGlb);
        var srcRoles = ImagesByRole(src);
        var dstRoles = ImagesByRole(dst);
        // Fall back to material order when the exporter renamed materials.
        if (!dstRoles.Keys.Any(srcRoles.ContainsKey))
        {
            srcRoles = srcRoles.ToDictionary(kv => kv.Key.Substring(kv.Key.IndexOf('/')), kv => kv.Value);
            dstRoles = dstRoles.ToDictionary(kv => kv.Key.Substring(kv.Key.IndexOf('/')), kv => kv.Value);
        }
        var replace = new Dictionary<int, (byte[] bytes, string mime)>();   // exported bufferView -> original image
        foreach (var (role, dImg) in dstRoles)
        {
            if (!srcRoles.TryGetValue(role, out int sImg)) continue;
            var si = src["images"][sImg].AsObject();
            var di = dst["images"][dImg].AsObject();
            if (si["bufferView"] == null || di["bufferView"] == null) continue;
            replace[di["bufferView"].GetValue<int>()] = (Slice(src, srcBin, si["bufferView"].GetValue<int>()), si["mimeType"]?.GetValue<string>() ?? "image/png");
            di["mimeType"] = si["mimeType"]?.GetValue<string>();
        }
        if (replace.Count == 0) return 0;

        // Repack every bufferView (4-byte aligned) so the new image sizes fit.
        var bvs = dst["bufferViews"].AsArray();
        using var outBin = new System.IO.MemoryStream();
        for (int i = 0; i < bvs.Count; i++)
        {
            var data = replace.TryGetValue(i, out var r) ? r.bytes : Slice(dst, dstBin, i);
            while (outBin.Length % 4 != 0) outBin.WriteByte(0);
            bvs[i]["byteOffset"] = (int)outBin.Length;
            bvs[i]["byteLength"] = data.Length;
            outBin.Write(data);
        }
        while (outBin.Length % 4 != 0) outBin.WriteByte(0);
        dst["buffers"][0]["byteLength"] = (int)outBin.Length;

        var jsonBytes = System.Text.Encoding.UTF8.GetBytes(dst.ToJsonString());
        int jsonPad = (4 - jsonBytes.Length % 4) % 4;
        using var f = System.IO.File.Create(exportedGlb);
        using var w = new System.IO.BinaryWriter(f);
        w.Write(0x46546C67u); w.Write(2u); w.Write((uint)(12 + 8 + jsonBytes.Length + jsonPad + 8 + outBin.Length));
        w.Write((uint)(jsonBytes.Length + jsonPad)); w.Write(0x4E4F534Au); w.Write(jsonBytes); for (int i = 0; i < jsonPad; i++) w.Write((byte)0x20);
        w.Write((uint)outBin.Length); w.Write(0x004E4942u); w.Write(outBin.ToArray());
        return replace.Count;
    }
}

