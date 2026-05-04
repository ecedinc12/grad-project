# isaac_backend/

Isaac Sim 5.1 headless SDG pipeline. Isaac Sim'in kendi Python'u (`/isaac-sim/python.sh`) ile çalışır.
Giriş noktası `main.py`; diğer modüller oradan çağrılır.

| Dosya | Açıklama |
|---|---|
| `main.py` | Pipeline giriş noktası: SimulationApp başlatma, sahne kurma, Replicator döngüsü |
| `config_loader.py` | `SceneConfig` JSON ve `assets/library.json` yükleme |
| `warehouse.py` | Layout seçici — `layouts/` paketine dispatch eder |
| `layout_planner.py` | Layout preset seçimi ve parametre çözümleme |
| `spawner.py` | Geofenced entity spawner ve hazard zone oluşturucu |
| `workers.py` | Worker karakterlerini Xform + USD ref olarak sahneye koyar, PPE görünürlüğünü ayarlar |
| `vehicle_animation.py` | Forklift/araç hareket rotaları |
| `animation.py` | IRA behavior extension yükleme ve worker davranışlarını bağlama |
| `ira_setup.py` | IRA extension yükleme, biped baking, anim graph bağlama |
| `command_injection.py` | IRA `AgentManager` üzerinden GoTo/Idle/LookAround komutları |
| `navmesh_utils.py` | Worker GoTo hedefleri için navmesh sorguları |
| `semantics.py` | USD semantik etiket uygulayıcı (`apply_usd_semantics`) |
| `lighting.py` | Kamera ve aydınlatma kurulumu |
| `log.py` | Pipeline adımları için stdout progress yardımcıları |

**Alt paketler:** `camera/`, `layouts/`, `behaviors/`
