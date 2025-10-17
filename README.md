# 视频播放量榜单（B站 + YouTube）

一个可搜索、聚合并排序展示多平台视频播放量的轻量项目。前端为单页`index.html`，后端采用`Flask`提供搜索任务与数据接口，支持异步抓取与结果合并，提供简单但实用的可视化榜单。

## 功能特性
- 平台支持：`bilibili` 与 `youtube`，可在前端勾选。
- 异步B站搜索：基于 `bilibili-api-python`，优先使用搜索结果 `pic` 作为封面；失败时尝试页面抓取；均失败则使用占位图。
- YouTube搜索：使用官方数据接口（需有效 API Key）。
- 结果合并：支持按标题相似度与缩略图相似度合并跨平台同一视频，按总播放量排序展示。
- 缩略图相似：统一去黑边与尺寸标准化，构建图片向量，计算余弦相似度。
- 前端榜单：
  - “平台链接”列，位于标题左侧，展示平台图标 + 链接。
  - 排名徽标优化：第1名/第2名/第3名显示金/银/铜。
  - 支持按总播放量、B站播放量、YouTube播放量排序。
  - 加载与错误提示、刷新按钮等基本交互。

## 目录结构
```
app.py            # Flask后端（主运行入口）
index.html        # 前端页面（单文件）
requirements.txt  # 依赖列表
README.md         # 本说明文档
```

## 环境依赖
在 `requirements.txt` 中已列出：
- Flask==3.0.0
- Flask-Cors==4.0.0
- requests==2.31.0
- beautifulsoup4==4.12.2
- bilibili-api-python==19.19.0
- numpy==1.26.0
- Pillow==10.1.0
- aiohttp==3.9.5

建议 Python 3.10+ 环境。

## 安装与运行
1. 安装依赖：
   ```bash
   pip install -r requirements.txt
   ```
2. 启动后端：
   ```bash
   python app.py
   ```
3. 打开浏览器访问：`http://127.0.0.1:5000/`

## 使用指南（前端）
- 输入关键词，选择平台（B站/YouTube）、是否勾选“使用缩略图匹配”。
- 点击“开始搜索”后显示任务进度；完成后自动渲染榜单。
- 榜单支持排序与刷新；左侧“平台链接”列可直达对应平台的原视频页面。
- 标题点击跳转主平台链接（默认取播放量更高的平台）。

## API 概述（后端）
- `POST /search`
  - 请求体：`{ keyword: string, platforms: string[], image_merge: boolean }`
  - 返回：`{ task_id: string }`
- `GET /task/<task_id>`
  - 返回任务状态：`pending/processing/completed/failed`
  - 字段：`progress`(0-100), `errors`(string[]), `results`（合并后的视频数组）
- `GET /platforms`
  - 返回支持的平台列表：`['bilibili', 'youtube']`
- 错误处理：对于 API 请求，404 返回 JSON 格式错误消息。

## 数据抓取与封面逻辑
- B站异步搜索（`search_bilibili_async`）
  - 使用 `search_by_type(keyword, SearchObjectType.VIDEO, order_type=OrderVideo.CLICK)` 分页搜索。
  - 详情（`get_video_info_async`）：通过 `video.Video(...).get_info()` 获取播放量与标题。
  - 缩略图优先级：
    1) 搜索结果项的 `pic`（自动补全为 `https:` 前缀）。
    2) 通过 `get_bilibili_thumbnail_from_page(url, title)` 从视频页按标题匹配提取；
    3) 失败则使用占位图 `https://picsum.photos/seed/{bv_id}/320/180`。
- 视频页封面抓取（`get_bilibili_thumbnail_from_page`）：
  - 两轮匹配策略：
    - 第一轮：从所有 `img` 标签中按 `alt` 精确匹配标题。
    - 第二轮：限定 `.b-img__inner` 类的 `img`，按 `alt` 精确匹配标题。
  - 统一补全链接为 `https://` 前缀。
  - 日志：将页面 HTML 写入 `logs/bili_pages/`，文件名 `BV号_清洗标题_时间戳.log`，便于定位抓取问题。
  - 注意：当前解析初始 HTML，可能存在 JS 延迟加载内容未获取的情况。

## 视频合并与排序
- 合并函数 `merge_videos`：
  - 标题相似度：`calculate_similarity(str1, str2)`（阈值 > 0.8）。
  - 缩略图相似度（当勾选“使用缩略图匹配”时）：> 0.95 视为匹配。
  - 合并后：统计总播放量，记录各平台链接与播放量；主平台为播放量更高者。
- 排序：按 `total_views` 降序，最终返回前 30 条结果。

## 图片向量与去黑边
- 函数 `get_image_vector(image_url)`：
  - 下载图片（`requests.get`，超时 10s），统一为 RGB。
  - 去黑边：以每像素最大通道值为亮度，亮度 ≤ 10 且行/列黑像素占比 ≥ 95% 视为黑边，裁剪上下左右。裁剪至少保留 8×8。
  - 尺寸标准化：裁剪后缩放到 `32×32`。
  - 向量化与归一化：展平为一维向量并 `L2` 归一化，输出 Python 列表。

## 配置与可选优化
- B站请求头与视频页请求头：在 `app.py` 常量 `HEADERS`、`VIDEO_PAGE_HEADERS` 中配置。
- YouTube API Key：`app.py` 中的 `YOUTUBE_API_KEY` 为示例，**请替换为你自己的 Key**。
- 优化建议：
  - 页面封面匹配失败时，可放宽标题匹配规则或使用更健壮的选择器。
  - 仅在抓取失败时写入 HTML 日志，减少日志量；或将扩展名改为 `.html`。
  - 若需要解析 JS 渲染后的页面，可引入无头浏览器（如 Playwright），但需另行集成与维护。

## 常见问题
- `aiohttp` 未安装导致客户端选择失败：已在 `requirements.txt` 添加；请确保安装成功。
- YouTube API Key 配额或无效：请在 `app.py` 中替换有效 Key，并注意配额限制。
- Windows 网络环境：若出现请求阻断，请检查代理或防火墙设置。

## 路线图
- 仅失败时记录页面 HTML，或按需开启/关闭日志记录。
- 支持更多平台（如抖音、快手等）。
- 引入更稳定的页面渲染解析（如 headless 浏览器）。
- 图片向量更精细的特征（如颜色直方图/感知哈希等）。

## 免责声明
- 数据源为公开平台接口或页面，结果仅供参考。
- 请合理使用，避免对平台造成过载或违反相关使用条款。
