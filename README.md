# Blender 指令小剧场

输入一句中文，后台调用本机 Blender 把模型摆成动作、渲成帧序列、再合成一段 mp4。

```
「挥手，然后鞠躬，再转一圈」
   ↓
解析成动作序列 [wave, bow, spin]
   ↓
Blender 建场景 → 导入模型 → 对骨骼插关键帧 → Workbench 渲帧
   ↓
frame_0001.png … frame_00NN.png  →  ffmpeg  →  stage.mp4
```

网页端就是一个输入框加一个播放器，没有前端框架，单个 `web/index.html`。

---

## 技术栈

| 层 | 用什么 |
| --- | --- |
| Web 服务 | FastAPI + uvicorn（`127.0.0.1:8765`） |
| 指令解析 | `engine/parser.py`，纯正则 + 别名表，无外部依赖 |
| 渲染 | 本机 Blender，`--background --python` 批处理 |
| 渲染引擎 | Blender 内置 `BLENDER_WORKBENCH`（960×540 @ 24fps，不走 Cycles） |
| 视频合成 | `imageio-ffmpeg` 自带的 ffmpeg，libx264 / yuv420p |
| 前端 | 无框架的原生 HTML + JS |

---

## 快速开始

需要 **Python 3.12**、**Blender 4.x 以上**（开发环境用的是 5.2），Windows。

```bat
:: 一条命令搞定（装依赖 + 起服务）
start.bat
```

或者手动来：

```bat
py -3.12 -m pip install -r requirements.txt
py -3.12 app.py
```

打开 <http://127.0.0.1:8765>，页面顶部会显示是否找到了 Blender（找不到时可以用环境变量 `BLENDER_EXE` 指定 `blender.exe`）。

### 想拿到 mp4 而不是逐帧播放

`requirements.txt` 里**没有** `imageio-ffmpeg`。不装的话 `run_stage()` 会静默跳过合成，前端会退化成用 canvas 按 24fps 播帧序列（画面一样，只是没有视频文件）。要成片就补一个：

```bat
py -3.12 -m pip install imageio-ffmpeg
```

### 支持的指令

按 `然后 / 接着 / 再 / 之后 / ， , ； ; 。` 切句，每句独立成一个动作，可重复。

| 动作 | 触发词（部分） |
| --- | --- |
| wave | 挥手、招手、打招呼、抬手 |
| walk | 走路、走两步、走 |
| bow | 鞠躬、弯腰 |
| sit | 坐下、坐下休息 |
| spin | 转圈、转身 |
| jump | 跳、跳跃、跳一下 |
| idle | 待机、站着、休息 |
| nod / shake | 点头 / 摇头 |
| clap | 鼓掌 |
| blink / wink | 眨眼、闭眼 / 挤眼、单眼眨 |
| smile | 微笑、笑 |
| talk | 张嘴、说话 |
| angry | 生气、皱眉 |

修饰词：`慢慢 / 缓慢 / 轻轻` → 0.6 倍速，`快速 / 赶快 / 急速 / 猛` → 1.6 倍速；
`三下 / 两圈 / 四步` 这类量词会变成重复次数（上限 6）。

---

## 架构与数据流

```
app.py                 FastAPI 入口；/api/status /api/models /api/play
  │
  ├─ engine/parser.py       中文指令 → [StageAction]
  ├─ engine/models.py       models/ 目录读写 + 同场角色（cast）解析
  ├─ engine/blender_runner.py  找 blender.exe → 写 job.json → 起子进程 → 收 result.json → 调 ffmpeg
  └─ engine/gmod.py         探测本机 GMod 安装与工坊订阅状态（只读，失败不影响主流程）
                              │
                              ▼
             blender_scripts/stage.py   （在 Blender 的 Python 里跑）
             清场景 → 布光/相机 → 导入模型或建方块人 → 插关键帧 → 存 stage.blend → 渲帧
                              │
                              ▼
             %LOCALAPPDATA%\couqie-stage\
               job.json  result.json  stage.blend  frames\frame_0001.png…  stage.mp4
```

**成片和中间产物不在仓库里**，落在 `%LOCALAPPDATA%\couqie-stage`（`engine/blender_runner.py:11`）。
这是刻意的：工程在桌面目录下时，渲染帧会让资源管理器反复刷新图标。

仓库根目录的 `output/` 是**另一回事**——那是 MDL→GLB 转换的工作区（解包工坊文件、vtf2tga 转换结果、探针输出），跟 Web 服务的运行无关。里面只有三个转换脚本会进仓库，见下一节。

### 运行环境要求：哪些能跨机，哪些绑死本机

这个问题很关键，答案分三层，**别把「别人跑不起来」当成 bug**。

| 能力 | 换台电脑能用吗 | 依赖 |
| --- | --- | --- |
| **网页服务 / 指令解析 / 播放成片** | ✅ 能 | Python 3.12 + `pip install -r requirements.txt` |
| **渲染任何 `.glb` 模型** | ✅ 能 | 任意 Blender 4.x+，路径靠 `find_blender()` 自动探测 |
| **把 GMod 工坊模型转成 `.glb`** | ❌ 不能 | 必须本机装有 Garry's Mod + 已订阅模型 |

**结论：下载这个仓库就能跑起来，但仓库里只有一个自制占位模型。想用真模型，得自己转。**

原因在 `output/convert_all.py:17-22`，三处硬编码（**都是 Steam/Blender 默认安装路径，不含用户名，但版本被钉死**）：

```python
GMOD_BIN  = Path(r"C:\Program Files (x86)\Steam\steamapps\common\GarrysMod\bin")
BLENDER   = Path(r"C:\Program Files\Blender Foundation\Blender 5.2\blender.exe")
VTF2TGA   = GMOD_BIN / "vtf2tga.exe"
```

为什么不能去掉依赖：

- `gmad.exe`（解包 `.gma`）和 `vtf2tga.exe`（`.vtf` → `.tga`）**是 Valve 随 GMod 一起装的官方工具**，没有独立发布版。想解包工坊订阅，只能靠它。
- GMod 本身需要 Steam 账号购买，且模型必须是你自己订阅过的。

要迁到别的机器，改上面三行常量即可。`engine/gmod.py` 已经是只读探测（找不到就返回提示），不会因为没有 GMod 而报错。

**另外一个硬性前提**：仓库不附带任何 `.mdl` / `.vtf` 源文件，`models/` 下只有自制的 `sample_penguin.glb`。转换链的输入全部来自你自己的 Steam 订阅。

### 模块职责

| 文件 | 行数 | 干什么 |
| --- | --- | --- |
| `app.py` | 117 | HTTP 层。`/api/play` 是唯一的主链路：解析 → 解析角色 → 调 Blender → 返回 mp4 路径 |
| `engine/parser.py` | 101 | 别名表 + 切句 + 速度/次数修饰词，输出 `StageAction(name, frames, repeats, speed)` |
| `engine/models.py` | 66 | 列出/校验/上传 `models/` 下的模型；把前端勾选的多个模型拼成 cast（上限 6 个）。`*_arms.glb` 这类第一人称手臂模型会被过滤掉——只有手没有躯干，放到舞台上就是一块浮空三角形 |
| `engine/blender_runner.py` | 123 | 定位 `blender.exe`（`BLENDER_EXE` → `Program Files\Blender Foundation\Blender*` → `%LOCALAPPDATA%\Programs` → `where blender`），写 job.json，起批处理子进程，读回 result.json，再用 ffmpeg 合成 mp4 |
| `engine/gmod.py` | 97 | 只读地探测 Steam 上的 GMod 安装（AppID **4000**，目录名是 `GarrysMod`）和 `appworkshop_4000.acf` 里的订阅数，给前端显示一句提示 |
| `blender_scripts/stage.py` | 579 | 整个渲染核心。方块人骨架、导入外部模型、骨骼别名表、15 个动作的关键帧、相机布光、渲帧 |
| `web/index.html` | 251 | 单页。状态探测、角色多选、模型上传、发指令、播成片（mp4 或 canvas 逐帧） |

### 骨骼是怎么对上的

外部模型（尤其是 GMod 的 Source 1 骨架）骨骼名千奇百怪，所以逻辑动作只认 15 个"逻辑骨"
（`Root / Spine / Head / L_UpperArm / …`），由 `BONE_ALIASES` 表映射到具体名字，
覆盖 ValveBiped（Source）、Mixamo、bip 系列和 Blender 内置命名。

还有两处 GMod 特有的坑，代码里都处理了：

- **铰链轴向不同**：方块人的铰链在局部 X 上，ValveBiped 的骨头指向 +X，同一个旋转要换成 Z（`remap_euler()`，`stage.py:191`）。
- **布料网格没有权重**：GMod PM 自带的裙摆面板（`Sm_PDSkirt_*`）完全没有蒙皮权重，不绑就会在世界空间里飘成一大片白帆。这些网格会被整体绑到 `Pelvis` 而不是删掉——删了包围盒会失真、取景就歪了（`stage.py:404-422`）。

---

## 模型来源与版权声明

**仓库里只有一个模型：`models/sample_penguin.glb`（137 KB，自制占位企鹅）。**

开发时用过的 BanG Dream! 的 MyGO!!!!! 角色（taki / soyo / raana / anon / tomori / saki）
来自 Steam 创意工坊的 Garry's Mod 订阅内容，**属于第三方版权作品**，
是 Valve / GMod 社区 / 各模型作者的成果。它们**不随本仓库分发**，
`.gitignore` 里已经用 `models/*.glb` + `!models/sample_penguin.glb` 挡掉了。

推论也请记住：**本仓库的软件代码许可证不覆盖任何模型资产**。用了别人的模型，责任在你。

### 自己转模型（工具在仓库里）

工坊角色是 Source 1 的 `.mdl`，需要转成 glb/fbx 才能导入。转换链已经写好了，三个脚本都在仓库里：

| 脚本 | 作用 |
| --- | --- |
| `output/mdl2glb.py` | 纯 Python 的 Source 1 `.mdl` 解析器（studiohdr / bodypart / 116 字节 mesh 记录 / 蒙皮权重 / VTF 贴图别名） |
| `output/mdl_to_blender.py` | 在 Blender 里跑，把 `.mdl` 建成带骨骼的网格并导出 GLB |
| `output/convert_all.py` | 批量入口：扫 `output/gmod_extract/`，逐个调 `mdl_to_blender.py`，结果写到 `models/` |

```bat
:: 1. 订阅并下载工坊内容（脚本默认从 GMod 的 bin\ 目录找 vtf2tga.exe）
::    GMod 安装路径写死在 output\convert_all.py:17，Blender 路径在 :18
:: 2. 把工坊内容解包到 output\gmod_extract\
:: 3. 转换
py -3.12 output\convert_all.py
```

解包出来的文件和 1.5 GB 的贴图中间产物都留在 `output/` 里，不进仓库；
`.gitignore` 里用 `output/**` 忽略整个目录、再单独反向包含上面三个 `.py`。

不想转也行——网页端支持直接上传 `.glb / .gltf / .fbx / .blend / .obj`。

---

## 已知限制

- **不是实时渲染**。每次点「生成小剧场」都要新起一个 Blender 进程、重建整个场景、重渲全部帧，
  十几秒起步。帧数多（`走两步` 一段就 64 帧）会更久。前端的"正在渲染…"是诚实的，它就是在等子进程。
- **Workbench 引擎**，不是 Cycles/EEVEE。快，但只有 studio 灯光 + 贴图色，没有阴影和反射。
- **ValveBiped 和内置方块人骨架轴向不同**，同一个动作在两套骨架上表现不完全一致。
  挥手这类动作尤其明显：ValveBiped 静止姿势是 T-pose，得先把大臂抬起来（`raise_arm = -70`），
  否则只有小臂在抽，看起来像抽搐而不是挥手。第三方骨架（Mixamo、bip 等）目前靠别名表兜底，
  骨骼名对不上的动作会被静默跳过。
- **不做口型、不做表情混合**。`talk` 只是把 `Jaw` 和 `Mouth` 缩放两下，没有 phoneme 时间轴。
- **模型是刚性对齐**。导入时按包围盒统一缩放到 1.7 米高并居中，
  两个身高差很多的角色同场会有点怪；没有 IK、没有落地贴合。
- **一次只渲一个任务**。`/api/play` 是同步阻塞的，没有任务队列，第二个请求会等第一个跑完。
- **Windows 优先**。`engine/gmod.py` 和 `blender_runner.py` 里的路径探测（`Program Files`、
  `where blender`）都是 Windows 专有的，macOS/Linux 上要自己改。
- **`/api/status` 会读 Steam 的 `appworkshop_4000.acf`**，只读，但毕竟碰了 Steam 的目录。
