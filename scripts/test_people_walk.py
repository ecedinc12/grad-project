"""
omni.anim.people yürüme testi
Çalıştırmak için:
  cd <isaac-sim-dizini>
  ./python.sh /path/to/test_people_walk.py

Çıktı:
  scripts/output/frames/  — her saniye 1 RGB frame (PNG)
  scripts/output/positions.csv  — karakter pozisyon logu
"""

import os
import csv

from isaacsim import SimulationApp

CONFIG = {
    "renderer": "RayTracedLighting",
    "headless": True,
    "width": 1280,
    "height": 720,
}
simulation_app = SimulationApp(CONFIG)

import carb
import omni.usd
import omni.kit.app
import omni.kit.commands
import omni.replicator.core as rep
from omni.isaac.core import World
from pxr import UsdGeom, Gf, Usd

# ---------------------------------------------------------------------------
# Ayarlar
# ---------------------------------------------------------------------------
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
COMMAND_FILE = os.path.join(SCRIPT_DIR, "people_commands.txt")
OUTPUT_DIR   = os.path.join(SCRIPT_DIR, "output")
FRAMES_DIR   = os.path.join(OUTPUT_DIR, "frames")
CSV_PATH     = os.path.join(OUTPUT_DIR, "positions.csv")

os.makedirs(FRAMES_DIR, exist_ok=True)

ASSETS_ROOT = carb.settings.get_settings().get("/persistent/isaac/asset_root/default")
if not ASSETS_ROOT:
    ASSETS_ROOT = "omniverse://localhost/NVIDIA/Assets/Isaac/4.2"

CHARACTER_ASSETS = f"{ASSETS_ROOT}/Isaac/People/Characters"

CHARACTERS = {
    "worker_01": f"{CHARACTER_ASSETS}/male_adult_construction_05/male_adult_construction_05.usd",
    "worker_02": f"{CHARACTER_ASSETS}/female_adult_construction_03/female_adult_construction_03.usd",
    "worker_03": f"{CHARACTER_ASSETS}/male_adult_construction_01/male_adult_construction_01.usd",
}

SPAWN_POSITIONS = {
    "worker_01": Gf.Vec3d(2.0,  0.0, 0.0),
    "worker_02": Gf.Vec3d(10.0, 5.0, 0.0),
    "worker_03": Gf.Vec3d(-3.0, 5.0, 0.0),
}

TOTAL_SECONDS    = 30.0
FPS              = 30
CAPTURE_INTERVAL = FPS       # her saniyede bir frame kaydet


# ---------------------------------------------------------------------------
# Extension
# ---------------------------------------------------------------------------
def enable_extensions():
    manager = omni.kit.app.get_app().get_extension_manager()
    for ext in ["omni.anim.people", "omni.anim.navigation"]:
        if not manager.is_extension_enabled(ext):
            print(f"[test] '{ext}' etkinleştiriliyor...")
            manager.set_extension_enabled_immediate(ext, True)
        else:
            print(f"[test] '{ext}' zaten aktif.")


# ---------------------------------------------------------------------------
# Sahne
# ---------------------------------------------------------------------------
def build_scene(world: World):
    stage = omni.usd.get_context().get_stage()

    world.scene.add_ground_plane(
        size=30.0,
        z_position=0.0,
        name="factory_floor",
        color=[0.3, 0.3, 0.35],
    )

    light_prim = stage.DefinePrim("/World/SunLight", "DistantLight")
    light_prim.GetAttribute("intensity").Set(3000.0)
    UsdGeom.Xformable(light_prim).AddRotateXYZOp().Set(Gf.Vec3f(-45, 0, 45))

    print("[test] Sahne kuruldu.")


# ---------------------------------------------------------------------------
# Navmesh
# ---------------------------------------------------------------------------
def setup_navmesh():
    """
    omni.anim.people GoTo komutlarının çalışması için navmesh gerekli.
    NavMeshVolume prim'i sahneleme alanını kapsayacak şekilde oluştur
    ve navmesh'i bake et.
    Bake başarısız olursa navmesh tabanlı navigasyonu devre dışı bırak
    (karakterler düz çizgide yürür, engel yok sayılır).
    """
    stage = omni.usd.get_context().get_stage()

    # NavMeshVolume: tüm sahneyi kapsayan kutu
    vol_path = "/World/NavMeshVolume"
    vol_prim = stage.DefinePrim(vol_path, "Cube")
    vol_prim.GetAttribute("size").Set(1.0)

    xform = UsdGeom.Xformable(vol_prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(5.0, 5.0, 1.0))   # sahne merkezi
    xform.AddScaleOp().Set(Gf.Vec3f(15.0, 15.0, 2.0))      # 30x30x4 m kutu

    # NavMesh sınıfı işaretçisi
    vol_prim.SetCustomDataByKey("omni:navmesh:volume", True)

    try:
        omni.kit.commands.execute("RebuildNavMesh")
        print("[test] NavMesh bake edildi.")
    except Exception as e:
        print(f"[test] NavMesh bake başarısız ({e}), doğrudan navigasyon aktif.")
        carb.settings.get_settings().set(
            "/persistent/omni/anim/people/navmeshBasedNavigation", False
        )


# ---------------------------------------------------------------------------
# Karakterler
# ---------------------------------------------------------------------------
def spawn_characters():
    stage = omni.usd.get_context().get_stage()

    if not stage.GetPrimAtPath("/World/Characters"):
        stage.DefinePrim("/World/Characters", "Xform")

    for name, asset_path in CHARACTERS.items():
        prim_path = f"/World/Characters/{name}"
        prim = stage.DefinePrim(prim_path, "Xform")
        prim.GetReferences().AddReference(asset_path)

        xform = UsdGeom.Xformable(prim)
        xform.ClearXformOpOrder()
        xform.AddTranslateOp().Set(SPAWN_POSITIONS[name])

        print(f"[test] Spawn: {name} @ {SPAWN_POSITIONS[name]}")


# ---------------------------------------------------------------------------
# omni.anim.people yapılandırma
# ---------------------------------------------------------------------------
def setup_people_simulation():
    settings = carb.settings.get_settings()
    settings.set("/persistent/omni/anim/people/commandFilePath", COMMAND_FILE)
    print(f"[test] Komut dosyası: {COMMAND_FILE}")

    # setup_characters: AnimGraph + BehaviorScript ekle
    for api_path in [
        ("omni.anim.people", "setup_characters"),
        ("omni.anim.people.scripts.global_agent_manager", "GlobalAgentManager"),
    ]:
        try:
            import importlib
            mod = importlib.import_module(api_path[0])
            fn  = getattr(mod, api_path[1])
            if api_path[1] == "GlobalAgentManager":
                fn().setup_characters()
            else:
                fn()
            print(f"[test] setup_characters OK ({api_path[0]})")
            return
        except Exception as e:
            print(f"[test] {api_path[0]}.{api_path[1]} başarısız: {e}")

    print("[test] UYARI: setup_characters otomatik yapılamadı.")
    print("[test]   → UI: Window > People Simulation > Setup Characters")


# ---------------------------------------------------------------------------
# Kamera + Replicator
# ---------------------------------------------------------------------------
def setup_camera_and_capture():
    stage = omni.usd.get_context().get_stage()
    cam_path = "/World/ObservationCamera"
    cam_prim = stage.DefinePrim(cam_path, "Camera")

    xform = UsdGeom.Xformable(cam_prim)
    xform.ClearXformOpOrder()
    xform.AddTranslateOp().Set(Gf.Vec3d(6.0, -8.0, 10.0))
    xform.AddRotateXYZOp().Set(Gf.Vec3f(-45.0, 0.0, 10.0))

    # Replicator render product + writer
    render_product = rep.create.render_product(cam_path, (1280, 720))

    writer = rep.WriterRegistry.get("BasicWriter")
    writer.initialize(output_dir=FRAMES_DIR, rgb=True)
    writer.attach([render_product])

    print(f"[test] Kamera ve frame capture hazır → {FRAMES_DIR}")
    return render_product


# ---------------------------------------------------------------------------
# Pozisyon okuma
# ---------------------------------------------------------------------------
def get_character_positions() -> dict:
    stage = omni.usd.get_context().get_stage()
    positions = {}
    for name in CHARACTERS:
        prim = stage.GetPrimAtPath(f"/World/Characters/{name}")
        if not prim.IsValid():
            continue
        xform    = UsdGeom.Xformable(prim)
        matrix   = xform.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
        pos      = matrix.ExtractTranslation()
        positions[name] = (round(pos[0], 3), round(pos[1], 3), round(pos[2], 3))
    return positions


# ---------------------------------------------------------------------------
# Simülasyon döngüsü
# ---------------------------------------------------------------------------
def run_simulation(world: World):
    total_steps = int(TOTAL_SECONDS * FPS)

    csv_file = open(CSV_PATH, "w", newline="")
    csv_writer = csv.writer(csv_file)
    csv_writer.writerow(["time_s", "character", "x", "y", "z"])

    print(f"\n[test] Simülasyon başlıyor: {TOTAL_SECONDS}s @ {FPS}fps")
    print(f"[test] Frameler: {FRAMES_DIR}")
    print(f"[test] Pozisyon logu: {CSV_PATH}")
    print("-" * 55)

    for step in range(total_steps):
        world.step(render=True)

        if step % CAPTURE_INTERVAL == 0:
            elapsed = step / FPS

            # Frame kaydet
            rep.orchestrator.step(rt_subframes=1)

            # Pozisyon oku ve logla
            positions = get_character_positions()
            for name, (x, y, z) in positions.items():
                csv_writer.writerow([f"{elapsed:.1f}", name, x, y, z])

            # Konsol özeti
            pos_str = "  ".join(
                f"{n.split('_')[1]}:({p[0]:.1f},{p[1]:.1f})"
                for n, p in positions.items()
            )
            print(f"[test] t={elapsed:5.1f}s  {pos_str}")

    csv_file.close()
    print("-" * 55)
    print("[test] Simülasyon tamamlandı.")


# ---------------------------------------------------------------------------
# Ana akış
# ---------------------------------------------------------------------------
def main():
    print("=" * 55)
    print("omni.anim.people Yürüme Testi")
    print("=" * 55)

    enable_extensions()

    world = World(stage_units_in_meters=1.0)
    world.initialize_simulation_context()

    build_scene(world)
    setup_navmesh()
    spawn_characters()
    setup_camera_and_capture()
    setup_people_simulation()

    # Birkaç warm-up adımı: extension'ların USD'yi işlemesi için
    for _ in range(5):
        simulation_app.update()

    world.reset()
    run_simulation(world)

    # Son durumu kaydet
    final_usd = os.path.join(OUTPUT_DIR, "final_scene.usd")
    omni.usd.get_context().save_as_stage(final_usd)
    print(f"[test] Sahne kaydedildi: {final_usd}")

    simulation_app.close()
    print("[test] Bitti.")


if __name__ == "__main__":
    main()
