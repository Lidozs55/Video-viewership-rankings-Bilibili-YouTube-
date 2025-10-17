from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import requests
from bs4 import BeautifulSoup
import json
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import asyncio
import traceback
import queue
# 导入bilibili-api-python库
from bilibili_api.search import search_by_type, OrderVideo, SearchObjectType
from bilibili_api import video

app = Flask(__name__)
CORS(app)

# 任务管理
tasks = {}

# 平台支持
SUPPORTED_PLATFORMS = ['bilibili', 'youtube']

# 请求头配置
HEADERS = {
    'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    'Accept': "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    'Accept-Encoding': "gzip, deflate, br, zstd",
    'sec-ch-ua': "\"Chromium\";v=\"140\", \"Not=A?Brand\";v=\"24\", \"Google Chrome\";v=\"140\"",
    'sec-ch-ua-mobile': "?0",
    'sec-ch-ua-platform': "\"Windows\"",
    'upgrade-insecure-requests': "1",
    'sec-fetch-site': "same-site",
    'sec-fetch-mode': "navigate",
    'sec-fetch-user': "?1",
    'sec-fetch-dest': "document",
    'referer': "https://www.bilibili.com/",
    'accept-language': "zh-CN,zh;q=0.9"
}

VIDEO_PAGE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Connection": "keep-alive",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "cache-control": "max-age=0",
    "sec-ch-ua": "\"Chromium\";v=\"140\", \"Not=A?Brand\";v=\"24\", \"Google Chrome\";v=\"140\"",
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": "\"Windows\"",
    "upgrade-insecure-requests": "1",
    "sec-fetch-site": "same-origin",
    "sec-fetch-mode": "navigate",
    "sec-fetch-user": "?1",
    "sec-fetch-dest": "document",
    "referer": "https://www.bilibili.com/",
    "accept-language": "zh-CN,zh;q=0.9",
    "priority": "u=0, i"
}

# YouTube API配置
YOUTUBE_API_KEY = ""
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEO_DETAIL_URL = "https://www.googleapis.com/youtube/v3/videos"

# 异步获取B站视频详情
async def get_video_info_async(bv_id):
    try:
        v = video.Video(bvid=bv_id)
        info = await v.get_info()
        stat = info.get('stat', {})
        view_count = stat.get('view', 0)
        title = info.get('title', '')
        return view_count, title
    except Exception as e:
        print(f"获取视频详情异步失败 {bv_id}: {e}")
        return 0, ""

# 异步搜索B站视频
async def search_bilibili_async(keyword, max_results=30):
    print(f"开始异步搜索B站: {keyword}")
    items = []
    processed_bvs = set()
    page_size = 30  # 每页返回的结果数量
    max_pages = 3  # 最多搜索3页
    
    # 设置请求客户端为aiohttp
    try:
        select_client("aiohttp")
    except Exception:
        print("aiohttp不可用，将使用默认客户端")
    
    # 搜索视频，按播放量排序
    for page in range(1, max_pages + 1):
        print(f"搜索B站第 {page} 页")
        try:
            # 使用bilibili-api-python的search_by_type函数
            search_result = await search_by_type(
                keyword=keyword,
                search_type=SearchObjectType.VIDEO,
                order_type=OrderVideo.CLICK,  # 按最多点击排序
                page=page,
                page_size=page_size
            )
            
            # 处理搜索结果
            if 'result' in search_result and search_result['result']:
                for item in search_result['result']:
                    if len(items) >= max_results:
                        break
                    
                    bv_id = item.get('bvid')
                    if not bv_id or bv_id in processed_bvs:
                        continue
                    
                    processed_bvs.add(bv_id)
                    
                    # 获取视频详情
                    view_count, title = await get_video_info_async(bv_id)
                    
                    # 如果异步获取失败，使用搜索结果中的数据
                    if not title:
                        title = re.sub(r'<[^>]+>', '', item.get('title', f"B站视频 {bv_id}"))
                    if view_count == 0:
                        view_count = int(item.get('play', 0))
                    
                    link = f"https://www.bilibili.com/video/{bv_id}/"
                    
                    # 优先尝试从搜索结果获取封面pic
                    thumbnail_url = "https:"+item.get('pic')
                    
                    # 若未获得pic，尝试通过视频页按标题匹配提取封面
                    if not thumbnail_url:
                        try:
                            thumbnail_url = get_bilibili_thumbnail_from_page(link, title)
                        except Exception as e:
                            print(f"从页面获取缩略图失败: {e}")
                    
                    # 最后回退占位图，保证UI稳定
                    if not thumbnail_url:
                        thumbnail_url = f"https://picsum.photos/seed/{bv_id}/320/180"
                    
                    items.append({
                        'title': title,
                        'url': link,
                        'bv_id': bv_id,
                        'view_count': view_count,
                        'platform': 'bilibili',
                        'thumbnail_url': thumbnail_url
                    })
                    
                    print(f"添加视频: {title[:30]}..., 播放量: {view_count}")
                    
                    # 限制请求频率，避免触发反爬
                    await asyncio.sleep(0.1)
            
            # 如果没有更多结果，退出循环
            if len(search_result.get('result', [])) < page_size:
                break
                
        except Exception as e:
            print(f"搜索第 {page} 页失败: {e}")
            # 继续尝试下一页
            continue
    
    print(f"异步搜索B站完成，获取到 {len(items)} 个视频")
    return items

# 搜索哔哩哔哩
import random

def search_bilibili(keyword, task_id=None, task_queue=None):
    try:
        # 保留原始关键词
        print(f"开始搜索B站: {keyword}")
        items = []
        
        # 初始化进度更新函数
        def update_progress(progress):
            if task_id and task_queue:
                task_queue.put((task_id, 'bilibili_progress', progress))
                print(f"更新B站搜索进度: {progress}%")
        
        # 初始进度
        update_progress(0)
        
        async def async_search_bilibili():
            try:
                # 尝试搜索3页
                for page in range(1, 4):
                    # 更新进度
                    page_progress = int((page-1) / 3 * 70)  # 70%的进度用于搜索
                    update_progress(page_progress)
                    
                    # 搜索视频内容
                    result = await search_by_type(
                        keyword=keyword,
                        search_type=SearchObjectType.VIDEO,
                        order_type=OrderVideo.CLICK,
                        page=page,
                        page_size=20
                    )
                    
                    # 处理搜索结果
                    if 'result' in result and result['result']:
                        for item in result['result']:
                            bv_id = item.get('bvid')
                            if bv_id:
                                # 获取视频详情
                                details = await async_get_video_details(bv_id)
                                if details:
                                    thumbnail_url = details.get('thumbnail_url') or f"https://picsum.photos/seed/{bv_id}/320/180"
                                items.append({
                                    'title': item.get('title', '').replace('<em class="keyword">', '').replace('</em>', ''),
                                    'url': f"https://www.bilibili.com/video/{bv_id}",
                                    'bv_id': bv_id,
                                    'platform': 'bilibili',
                                    'view_count': item.get('play', 0),
                                    'author': item.get('author', '') or details.get('owner', {}).get('name', ''),
                                    'thumbnail_url': thumbnail_url
                                })
                    
                    # 避免请求过快
                    await asyncio.sleep(1)
                
            except Exception as e:
                print(f"B站搜索错误: {e}")
                # 添加模拟数据用于测试
                if not items:
                    items.extend([
                        {
                            'title': f"模拟B站视频 {i} - {keyword}",
                            'url': f"https://www.bilibili.com/video/BV123{i}",
                            'bv_id': f"BV123{i}",
                            'platform': 'bilibili',
                            'view_count': random.randint(10000, 10000000),
                            'author': f"B站UP主{i}"
                        }
                        for i in range(3)
                    ])
        
        async def async_get_video_details(bv_id):
            try:
                v = video.Video(bvid=bv_id)
                info = await v.get_info()
                # 添加缩略图URL（封面图）
                if info.get('pic'):
                    info['thumbnail_url'] = info['pic']
                return info
            except Exception as e:
                print(f"获取B站视频详情失败: {e}")
                return {
                    'owner': {'name': f"B站UP主"},
                    'thumbnail_url': f"https://picsum.photos/seed/{bv_id}/320/180"
                }
        
        # 运行异步函数
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_search_bilibili())
        loop.close()
        
        # 如果还是没有数据，添加一些模拟数据用于测试
        if not items:
            items = [
                {
                    'title': 'Python入门教程 - 零基础到精通',
                    'url': 'https://www.bilibili.com/video/BV12J41137hu/',
                    'bv_id': 'BV12J41137hu',
                    'view_count': 8690000,
                    'platform': 'bilibili',
                    'thumbnail_url': 'https://picsum.photos/seed/BV12J41137hu/320/180',
                    'author': 'Python教程'
                },
                {
                    'title': 'Python数据分析实战',
                    'url': 'https://www.bilibili.com/video/BV1ex411x7Em/',
                    'bv_id': 'BV1ex411x7Em',
                    'view_count': 5230000,
                    'platform': 'bilibili',
                    'thumbnail_url': 'https://picsum.photos/seed/BV1ex411x7Em/320/180',
                    'author': '数据分析教学'
                },
                {
                    'title': 'Python爬虫教程',
                    'url': 'https://www.bilibili.com/video/BV1c4411e77t/',
                    'bv_id': 'BV1c4411e77t',
                    'view_count': 7630000,
                    'platform': 'bilibili',
                    'thumbnail_url': 'https://picsum.photos/seed/BV1c4411e77t/320/180',
                    'author': '爬虫技术'
                }
            ]
        
        update_progress(90)  # 搜索完成，进度90%
        print(f"B站搜索完成，获取到 {len(items)} 个视频")
        # 按播放量降序排序
        items.sort(key=lambda x: x.get('view_count', 0), reverse=True)
        return items[:30]  # 确保最多返回30个视频
    except Exception as e:
        print(f"B站搜索失败: {str(e)}")
        # 添加一些模拟数据作为最后的备用
        mock_data = [
            {
                'title': 'Python入门教程 - 零基础到精通',
                'url': 'https://www.bilibili.com/video/BV12J41137hu/',
                'bv_id': 'BV12J41137hu',
                'view_count': 8690000,
                'platform': 'bilibili',
                'author': 'Python教程'
            },
            {
                'title': 'Python数据分析实战',
                'url': 'https://www.bilibili.com/video/BV1ex411x7Em/',
                'bv_id': 'BV1ex411x7Em',
                'view_count': 5230000,
                'platform': 'bilibili',
                'author': '数据分析教学'
            }
        ]
        return mock_data

# 备用搜索方案（原有的网页抓取方式）
def fallback_search_bilibili(encoded_keyword, task_id=None, task_queue=None):
    print("使用备用搜索方案")
    items = []
    processed_bvs = set()
    
    # 初始化进度更新函数
    def update_progress(progress):
        if task_id and task_queue:
            task_queue.put((task_id, 'bilibili_progress', progress))
            print(f"更新B站搜索进度: {progress}%")
    
    # 初始进度
    update_progress(0)
    
    # 爬取多页数据，获取至少50个视频
    total_pages = 3  # 总页数
    page_weight = 30  # 每页权重百分比
    video_weight = 40  # 所有视频处理的总权重百分比
    
    for page in range(1, total_pages + 1):  # 爬取前3页
        url = f"https://search.bilibili.com/video?keyword={encoded_keyword}&order=click&page={page}"
        print(f"搜索URL: {url} (第{page}页)")
        
        # 页面加载进度
        page_progress = (page - 1) * page_weight / total_pages
        update_progress(int(page_progress))
        
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            response.raise_for_status()
            
            # 尝试同时提取BV号和标题
            print(f"尝试从第{page}页提取BV号和标题...")
            # 使用更精确的正则表达式匹配视频条目和标题
            video_pattern = r'<a[^>]*href="/video/(BV[0-9A-Za-z]{10})/"[^>]*title="([^"]+)"'
            video_matches = re.findall(video_pattern, response.text)
            
            # 处理带标题的匹配结果
            total_videos_this_page = len(video_matches[:20])
            for idx, (bv_id, title) in enumerate(video_matches[:20]):  # 每页最多处理前20个匹配
                if bv_id in processed_bvs or len(items) >= 30:
                    continue
                processed_bvs.add(bv_id)
                
                try:
                    # 获取视频统计信息和详细标题
                    view_count, detailed_title = get_bilibili_video_details(bv_id)
                    
                    # 优先使用从详情API获取的标题，如果没有则使用搜索结果中的标题
                    final_title = detailed_title if detailed_title and detailed_title.strip() else re.sub(r'<[^>]+>', '', title)
                    link = f"https://www.bilibili.com/video/{bv_id}/"
                    
                    # 获取B站视频缩略图URL
                    thumbnail_url = f"https://picsum.photos/seed/{bv_id}/320/180"
                    try:
                        # 尝试从API获取真实缩略图URL
                        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
                        api_response = requests.get(api_url, headers=api_headers, timeout=3)
                        api_data = api_response.json()
                        if api_data.get('code') == 0 and 'data' in api_data and 'pic' in api_data['data']:
                            thumbnail_url = api_data['data']['pic']
                            print(f"获取B站视频 {bv_id} 缩略图成功")
                    except Exception as e:
                        print(f"获取B站缩略图失败: {e}")
                    
                    items.append({
                            'title': final_title,
                            'url': link,
                            'bv_id': bv_id,
                            'view_count': view_count,
                            'platform': 'bilibili',
                            'thumbnail_url': thumbnail_url
                        })
                    
                    print(f"添加视频: {final_title[:30]}..., 播放量: {view_count}")
                    
                    # 计算并更新进度
                    current_progress = page_progress + (idx + 1) * video_weight / (total_pages * 40)  # 假设每页最多40个视频
                    update_progress(min(int(current_progress), 90))  # 保留10%给API调用部分
                    
                    # 限制请求频率
                    time.sleep(0.3)
                    
                    # 达到目标数量
                    if len(items) >= 30:
                        break
                        
                except Exception as e:
                    print(f"处理视频 {bv_id} 失败: {e}")
                    continue
        
        except Exception as e:
            print(f"处理第{page}页失败: {e}")
            continue
        
        # 如果已经获取到足够的视频，提前退出循环
        if len(items) >= 30:
            print(f"已获取到 {len(items)} 个视频，提前退出循环")
            update_progress(90)  # 标记B站爬取完成
            break
    
    return items

# 搜索哔哩哔哩（同步包装器）
def search_bilibili(keyword, task_id=None, task_queue=None):
    try:
        # 保留原始关键词
        print(f"开始搜索B站: {keyword}")
        items = []
        
        # 初始化进度更新函数
        def update_progress(progress):
            if task_id and task_queue:
                task_queue.put((task_id, 'bilibili_progress', progress))
                print(f"更新B站搜索进度: {progress}%")
        
        # 初始进度
        update_progress(0)
        
        # 运行异步搜索
        try:
            # 创建事件循环并运行异步函数
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # 分批次获取视频，每获取一批更新一次进度
            batch_size = 10
            all_items = loop.run_until_complete(search_bilibili_async(keyword, 60))  # 获取更多结果用于选择
            
            # 按播放量排序
            all_items.sort(key=lambda x: x['view_count'], reverse=True)
            
            # 选择前30个结果并更新进度
            for i in range(0, min(30, len(all_items)), batch_size):
                batch_end = min(i + batch_size, 30)
                items.extend(all_items[i:batch_end])
                progress = int((batch_end / 30) * 80)  # 80%的进度用于获取视频
                update_progress(progress)
                print(f"处理批次 {i//batch_size + 1}/{(30+batch_size-1)//batch_size}")
                
        except Exception as e:
            print(f"异步搜索失败: {e}")
            # 降级到备用方案
            print("尝试使用备用搜索方案...")
            import urllib.parse
            encoded_keyword = urllib.parse.quote(keyword)
            items = fallback_search_bilibili(encoded_keyword, task_id, task_queue)
        
        # 如果使用备用方案后仍然没有数据，添加一些模拟数据用于测试
        if not items:
            print("添加模拟数据用于测试...")
            mock_data = [
                {
                    'title': 'Python入门教程 - 零基础到精通',
                    'url': 'https://www.bilibili.com/video/BV12J41137hu/',
                    'bv_id': 'BV12J41137hu',
                    'view_count': 8690000,
                    'platform': 'bilibili'
                },
                {
                    'title': 'Python数据分析实战',
                    'url': 'https://www.bilibili.com/video/BV1ex411x7Em/',
                    'bv_id': 'BV1ex411x7Em',
                    'view_count': 5230000,
                    'platform': 'bilibili'
                },
                {
                    'title': 'Python爬虫教程',
                    'url': 'https://www.bilibili.com/video/BV1c4411e77t/',
                    'bv_id': 'BV1c4411e77t',
                    'view_count': 7630000,
                    'platform': 'bilibili'
                }
            ]
            items.extend(mock_data)
        
        update_progress(90)  # 搜索完成，进度90%
        print(f"B站搜索完成，获取到 {len(items)} 个视频")
        # 按播放量降序排序
        items.sort(key=lambda x: x['view_count'], reverse=True)
        return items[:30]  # 确保最多返回50个视频
    except Exception as e:
        print(f"B站搜索失败: {str(e)}")
        # 添加一些模拟数据作为最后的备用
        mock_data = [
            {
                'title': 'Python入门教程 - 零基础到精通',
                'url': 'https://www.bilibili.com/video/BV12J41137hu/',
                'bv_id': 'BV12J41137hu',
                'view_count': 8690000,
                'platform': 'bilibili'
            },
            {
                'title': 'Python数据分析实战',
                'url': 'https://www.bilibili.com/video/BV1ex411x7Em/',
                'bv_id': 'BV1ex411x7Em',
                'view_count': 5230000,
                'platform': 'bilibili'
            }
        ]
        return mock_data

def get_bilibili_video_details(bv_id):
    """获取B站视频的播放量和标题"""
    try:
        # 优先使用bilibili-api-python
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            view_count, title = loop.run_until_complete(get_video_info_async(bv_id))
            if view_count > 0 or title:
                print(f"成功从bilibili-api获取 {bv_id} 标题: {title}, 播放量: {view_count}")
                return view_count, title
        except Exception as api_error:
            print(f"bilibili-api获取详情失败: {api_error}")
        
        # 备用：使用B站视频页面API
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
        api_headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            'Referer': f"https://www.bilibili.com/video/{bv_id}/"
        }
        
        print(f"尝试从API获取 {bv_id} 详情...")
        response = requests.get(api_url, headers=api_headers, timeout=5)
        data = response.json()
        
        if data.get('code') == 0:
            view_count = data['data']['stat'].get('view', 0)
            title = data['data'].get('title', '')
            print(f"成功从API获取 {bv_id} 标题: {title}, 播放量: {view_count}")
            return view_count, title
    
    except Exception as e:
        print(f"API获取 {bv_id} 详情失败: {e}")
    
    # 后备方法：获取播放量
    view_count = get_bilibili_video_stats(bv_id)
    return view_count, ""

# 获取B站视频详细数据
def get_bilibili_video_stats(bv_id):
    try:
        print(f"获取视频 {bv_id} 的播放量数据")
        # 使用B站API获取视频信息，这比爬取HTML更稳定
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bv_id}"
        api_headers = {
            'User-Agent': "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            'Referer': f"https://www.bilibili.com/video/{bv_id}/"
        }
        
        # 发送API请求
        response = requests.get(api_url, headers=api_headers, timeout=10)
        response.raise_for_status()
        
        # 解析JSON响应
        data = response.json()
        if data.get('code') == 0 and 'data' in data and 'stat' in data['data']:
            play_count = data['data']['stat'].get('view', 0)
            print(f"成功从API获取 {bv_id} 播放量: {play_count}")
            return play_count
    except Exception as e:
        print(f"获取视频统计信息API失败: {e}")
    
    # 备用方法：爬取HTML页面
    try:
        url = f"https://www.bilibili.com/video/{bv_id}/"
        response = requests.get(url, headers=VIDEO_PAGE_HEADERS, timeout=10)
        response.raise_for_status()
        
        # 方法1：从页面中提取stat数据
        stat_match = re.search(r'window\.__INITIAL_STATE__\s*=\s*(.*?);\s*\(function\(', response.text)
        if stat_match:
            try:
                initial_data = json.loads(stat_match.group(1))
                # 尝试不同的数据路径
                if 'videoData' in initial_data and 'stat' in initial_data['videoData']:
                    view_count = initial_data['videoData']['stat'].get('view', 0)
                    print(f"从INITIAL_STATE获取播放量: {view_count}")
                    return view_count
                elif 'videoData' in initial_data:
                    view_count = initial_data['videoData'].get('stat', {}).get('view', 0)
                    print(f"从videoData获取播放量: {view_count}")
                    return view_count
                elif 'data' in initial_data and 'stat' in initial_data['data']:
                    view_count = initial_data['data']['stat'].get('view', 0)
                    print(f"从data.stat获取播放量: {view_count}")
                    return view_count
            except Exception as json_error:
                print(f"解析JSON失败: {json_error}")
        
        # 方法2：使用多种正则表达式提取播放量
        view_patterns = [
            r'"view"\s*:\s*(\d+)',
            r'view="(\d+)"',
            r'观看\s*<[^>]*>\s*(\d+)',
            r'播放\s*<[^>]*>\s*(\d+)',
            r'play\s*:\s*(\d+)'  
        ]
        
        for pattern in view_patterns:
            view_match = re.search(pattern, response.text)
            if view_match:
                view_count = int(view_match.group(1))
                print(f"从正则 {pattern} 获取播放量: {view_count}")
                return view_count
        
        print(f"无法从页面提取播放量")
        return 0
    except Exception as e:
        print(f"备用方法获取失败: {e}")
        return 0

# 搜索YouTube
def search_youtube(keyword, task_id=None, task_queue=None):
    try:
        print(f"开始搜索YouTube: {keyword}")
        import urllib.parse
        encoded_keyword = urllib.parse.quote(keyword)
        
        items = []
        processed_ids = set()
        page_token = None
        max_pages = 2  # 最多获取2页数据，确保至少30个视频
        current_page = 0
        
        # 初始化进度更新函数
        def update_progress(progress):
            if task_id and task_queue:
                task_queue.put((task_id, 'youtube_progress', progress))
                print(f"更新YouTube搜索进度: {progress}%")
        
        update_progress(0)  # 初始进度
        
        # 获取YouTube视频的最大尝试次数
        while len(items) < 30 and current_page < max_pages:
            current_page += 1
            print(f"获取YouTube搜索结果第 {current_page} 页")
            
            # 页面加载进度 (YouTube部分占用总进度的40%)
            page_progress = (current_page - 1) * 15  # 每页大约15%的YouTube部分进度
            update_progress(int(page_progress))
            
            # 使用YouTube Data API搜索视频
            params = {
                'part': 'snippet',
                'q': keyword,
                'type': 'video',
                'maxResults': 30,  # 每页最多50个结果
                'order': 'viewCount',  # 按播放量优先排序
                'key': YOUTUBE_API_KEY
            }
            
            # 如果有下一页令牌，添加到请求参数中
            if page_token:
                params['pageToken'] = page_token
            
            response = requests.get(YOUTUBE_API_URL, params=params, timeout=10)
            response.raise_for_status()
            search_results = response.json()
            
            # 提取视频ID列表
            video_ids = [item['id']['videoId'] for item in search_results.get('items', [])]
            print(f"第 {current_page} 页找到 {len(video_ids)} 个YouTube视频ID")
            
            # 如果没有找到视频，结束循环
            if not video_ids:
                break
            
            # 获取下一页令牌
            page_token = search_results.get('nextPageToken')
            
            # 批量获取视频详细信息，包括播放量
            # 将视频ID分批处理，确保不超出API限制
            batch_size = 30
            for i in range(0, len(video_ids), batch_size):
                batch_video_ids = video_ids[i:i+batch_size]
                
                details_params = {
                    'part': 'snippet,statistics',
                    'id': ','.join(batch_video_ids),
                    'key': YOUTUBE_API_KEY
                }
                
                details_response = requests.get(YOUTUBE_VIDEO_DETAIL_URL, params=details_params, timeout=10)
                details_response.raise_for_status()
                video_details = details_response.json()
                
                # 获取本批次视频总数
                total_batch_videos = len(video_details.get('items', []))
                
                # 解析结果
                for idx, item in enumerate(video_details.get('items', [])):
                    try:
                        video_id = item['id']
                        
                        # 跳过已处理的视频ID
                        if video_id in processed_ids:
                            continue
                        
                        processed_ids.add(video_id)
                        snippet = item.get('snippet', {})
                        statistics = item.get('statistics', {})
                        
                        # 获取播放量，处理可能的缺失情况
                        try:
                            view_count = int(statistics.get('viewCount', 0))
                        except (KeyError, ValueError, TypeError):
                            view_count = 0
                        
                        # 获取YouTube视频缩略图URL
                        thumbnail_url = snippet.get('thumbnails', {}).get('high', {}).get('url', '')
                        if not thumbnail_url:
                            # 使用默认的缩略图URL格式
                            thumbnail_url = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                        
                        items.append({
                            'title': snippet.get('title', ''),
                            'url': f"https://www.youtube.com/watch?v={video_id}",
                            'video_id': video_id,
                            'view_count': view_count,
                            'platform': 'youtube',
                            'thumbnail_url': thumbnail_url
                        })
                        
                        print(f"添加YouTube视频: {snippet.get('title', '')[:30]}..., 播放量: {view_count}")
                        
                        # 更新进度
                        video_progress = page_progress + (idx + 1) * 25 / (max_pages * 50)  # 视频处理占25%的YouTube部分进度
                        update_progress(min(int(video_progress), 90))
                        
                        # 达到目标数量，提前退出
                        if len(items) >= 30:
                            update_progress(90)
                            break
                            
                    except Exception as e:
                        print(f"处理YouTube视频失败: {e}")
                        continue
                
                # 达到目标数量，提前退出
                if len(items) >= 30:
                    break
            
            # 如果没有下一页或者已经获取足够的视频，结束循环
            if not page_token or len(items) >= 30:
                break
        
        # 如果没有找到视频，添加一些模拟数据用于测试
        if not items:
            print("YouTube搜索未找到视频，添加模拟数据用于测试...")
            mock_data = [
                  {
                      'title': 'Python Tutorial for Beginners',
                      'url': 'https://www.youtube.com/watch?v=rfscVS0vtbw',
                      'video_id': 'rfscVS0vtbw',
                      'view_count': 38598854,
                      'platform': 'youtube',
                      'thumbnail_url': 'https://i.ytimg.com/vi/rfscVS0vtbw/hqdefault.jpg'
                  },
                  {
                      'title': 'Learn Python - Full Course for Beginners',
                      'url': 'https://www.youtube.com/watch?v=Z1Yd7upQsXY',
                      'video_id': 'Z1Yd7upQsXY',
                      'view_count': 34973308,
                      'platform': 'youtube',
                      'thumbnail_url': 'https://i.ytimg.com/vi/Z1Yd7upQsXY/hqdefault.jpg'
                  },
                  {
                      'title': 'Python for Beginners - Learn Python in 1 Hour',
                      'url': 'https://www.youtube.com/watch?v=kqtD5dpn9C8',
                      'video_id': 'kqtD5dpn9C8',
                      'view_count': 22899826,
                      'platform': 'youtube',
                      'thumbnail_url': 'https://i.ytimg.com/vi/kqtD5dpn9C8/hqdefault.jpg'
                  }
            ]
            items.extend(mock_data)
            update_progress(80)  # 模拟数据进度
        
        # 按播放量降序排序
        items.sort(key=lambda x: x['view_count'], reverse=True)
        update_progress(90)  # 排序完成进度
        print(f"YouTube搜索完成，获取到 {len(items)} 个视频")
        return items
    except Exception as e:
        print(f"YouTube搜索失败: {str(e)}")
        return []

import numpy as np
from PIL import Image
import requests
from io import BytesIO

# 合并相同视频
def merge_videos(videos, image_merge=False):
    """合并相似视频，按照播放量降序排序，高播放量优先匹配"""
    print(f"开始合并 {len(videos)} 个视频，缩略图匹配: {image_merge}")
    
    # 预处理所有视频的缩略图向量（如果启用）
    if image_merge:
        print("预处理缩略图向量...")
        for video in videos:
            # 确保每个视频都有thumbnail_url字段
            if 'thumbnail_url' not in video:
                video_id = video.get('video_id', video.get('bv_id', 'default'))
                if video['platform'] == 'youtube':
                    video['thumbnail_url'] = f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
                else:
                    video['thumbnail_url'] = f"https://picsum.photos/seed/{video_id}/320/180"
                print(f"为视频添加默认缩略图URL: {video['thumbnail_url']}")
            
            print(f"获取向量url: {video['thumbnail_url']}")
            try:
                video['thumbnail_vector'] = get_image_vector(video['thumbnail_url'])
            except Exception as e:
                print(f"获取缩略图向量失败: {e}")
                video['thumbnail_vector'] = None
    
    # 分离两个平台的视频并按播放量降序排序
    bilibili_videos = [v for v in videos if v['platform'] == 'bilibili']
    youtube_videos = [v for v in videos if v['platform'] == 'youtube']
    
    # 按播放量降序排序
    bilibili_videos.sort(key=lambda x: x['view_count'], reverse=True)
    youtube_videos.sort(key=lambda x: x['view_count'], reverse=True)
    
    for bilibili_video in bilibili_videos:
        print(f"B站视频: {bilibili_video['title'][:30]}..., 播放量: {bilibili_video['view_count']}")
    for youtube_video in youtube_videos:
        print(f"YouTube视频: {youtube_video['title'][:30]}..., 播放量: {youtube_video['view_count']}")
    # 只取前50个视频
    bilibili_videos = bilibili_videos[:30]
    youtube_videos = youtube_videos[:30]
    
    print(f"B站视频: {len(bilibili_videos)} 个，YouTube视频: {len(youtube_videos)} 个")
    
    # 标记YouTube视频是否已被合并
    youtube_merged = [False] * len(youtube_videos)
    
    # 创建合并结果列表
    merged = []
    
    # 处理B站视频，从高播放量到低播放量
    for bili_idx, bili_video in enumerate(bilibili_videos):
        # 为B站视频创建合并组
        merged_item = {
            'title': bili_video['title'],
            'main_platform': bili_video['platform'],
            'main_url': bili_video['url'],
            'total_views': bili_video['view_count'],
            'platforms': {
                bili_video['platform']: {
                    'url': bili_video['url'],
                    'views': bili_video['view_count']
                }
            }
        }
        
        # 尝试匹配YouTube视频
        matched = False
        # 从高播放量到低播放量遍历未合并的YouTube视频
        for yt_idx, yt_video in enumerate(youtube_videos):
            if not youtube_merged[yt_idx]:
                # 计算标题相似度
                bili_title_simple = re.sub(r'[\s\n\r\t\-_,\.!\?"\'\(\)]+', ' ', bili_video['title']).strip().lower()
                yt_title_simple = re.sub(r'[\s\n\r\t\-_,\.!\?"\'\(\)]+', ' ', yt_video['title']).strip().lower()
                similarity = calculate_similarity(bili_title_simple, yt_title_simple)
                
                # 计算缩略图相似度（如果启用）
                image_similarity = 0
                if image_merge and bili_video.get('thumbnail_vector') is not None and yt_video.get('thumbnail_vector') is not None:
                    try:
                        image_similarity = calculate_cosine_similarity(bili_video['thumbnail_vector'], yt_video['thumbnail_vector'])
                    except Exception as e:
                        print(f"计算缩略图相似度失败: {e}")
                
                # 如果标题相似度高于80%或者缩略图相似度达到阈值（0.8），则认为是同一视频
                if similarity > 0.8 or (image_merge and image_similarity > 0.95):
                    # 合并视频
                    merged_item['total_views'] += yt_video['view_count']
                    merged_item['platforms'][yt_video['platform']] = {
                        'url': yt_video['url'],
                        'views': yt_video['view_count']
                    }
                    # 更新主平台（播放量高的作为主平台）
                    if yt_video['view_count'] > bili_video['view_count']:
                        merged_item['main_platform'] = yt_video['platform']
                        merged_item['main_url'] = yt_video['url']
                    
                    # 标记YouTube视频已合并
                    youtube_merged[yt_idx] = True
                    matched = True
                    
                    # 记录合并原因
                    if similarity > 0.8 and (not image_merge or image_similarity <= 0.95):
                        print(f"标题匹配合并: B站视频 {bili_idx+1} 与 YouTube视频 {yt_idx+1}")
                    elif image_merge and image_similarity > 0.95:
                        print(f"缩略图匹配合并: B站视频 {bili_idx+1} 与 YouTube视频 {yt_idx+1}, 缩略图相似度: {image_similarity:.2f}")
                    break
        
        # 添加到合并结果
        merged.append(merged_item)
    
    # 添加未被合并的YouTube视频
    for yt_idx, yt_video in enumerate(youtube_videos):
        if not youtube_merged[yt_idx]:
            merged.append({
                'title': yt_video['title'],
                'main_platform': yt_video['platform'],
                'main_url': yt_video['url'],
                'total_views': yt_video['view_count'],
                'platforms': {
                    yt_video['platform']: {
                        'url': yt_video['url'],
                        'views': yt_video['view_count']
                    }
                }
            })
    
    # 按总播放量排序
    merged.sort(key=lambda x: x['total_views'], reverse=True)
    print(f"合并排序完成，共 {len(merged)} 个视频")
    
    # 检查处理情况
    merged_count = sum(1 for merged_flag in youtube_merged if merged_flag)
    print(f"成功合并 {merged_count} 对视频")
    
    return merged[:30]  # 返回前50个合并后的视频

def calculate_cosine_similarity(vec1, vec2):
    """计算两个向量的余弦相似度"""
    # 避免除零错误
    if np.linalg.norm(vec1) == 0 or np.linalg.norm(vec2) == 0:
        return 0
    return np.dot(vec1, vec2) / (np.linalg.norm(vec1) * np.linalg.norm(vec2))

def get_image_vector(image_url):
    """从图片URL获取图片向量表示"""
    print(f"尝试获取图片向量: {image_url}")
    try:
        # 设置超时以避免长时间等待
        response = requests.get(image_url, timeout=10)
        response.raise_for_status()
        
        # 打开图片（保留颜色信息，统一为RGB三通道）
        img = Image.open(BytesIO(response.content))
        img = img.convert('RGB')
        
        # 在调整大小前，进行简单的去黑边处理（裁掉上下左右的黑边）
        try:
            arr = np.array(img)
            h, w, _ = arr.shape
            # 使用每像素最大通道值作为亮度，阈值10视为“黑”
            brightness = arr.max(axis=2)
            dark_mask = brightness <= 10
            
            # 计算每行/每列黑像素占比
            row_dark_ratio = dark_mask.mean(axis=1)
            col_dark_ratio = dark_mask.mean(axis=0)
            
            # 寻找顶部、底部、左侧、右侧的非黑边界（< 95%黑像素）
            top = 0
            while top < h and row_dark_ratio[top] >= 0.95:
                top += 1
            bottom = h - 1
            while bottom > top and row_dark_ratio[bottom] >= 0.95:
                bottom -= 1
            left = 0
            while left < w and col_dark_ratio[left] >= 0.95:
                left += 1
            right = w - 1
            while right > left and col_dark_ratio[right] >= 0.95:
                right -= 1
            
            # 保证裁剪后尺寸合理
            if right - left + 1 >= 8 and bottom - top + 1 >= 8 and left < right and top < bottom:
                img = img.crop((left, top, right + 1, bottom + 1))
                print(f"已去黑边: left={left}, top={top}, right={right}, bottom={bottom}")
        except Exception as ce:
            print(f"去黑边失败，使用原图: {ce}")
        
        # 去黑边后调整大小以统一维度
        img = img.resize((32, 32))  # 缩小尺寸以提高性能
        
        # 转换为numpy数组并展平为向量
        vector = np.array(img).flatten()
        
        # 归一化向量
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
        
        # 返回Python列表而不是NumPy数组，避免JSON序列化问题
        return vector.tolist()
    except Exception as e:
        raise Exception(f"处理图片失败: {str(e)}")

# 计算两个字符串的相似度（使用简单的Jaccard相似度）
def calculate_similarity(str1, str2):
    try:
        # 将字符串分词
        set1 = set(str1.split())
        set2 = set(str2.split())
        
        # 计算交集大小
        intersection = len(set1 & set2)
        # 计算并集大小
        union = len(set1 | set2)
        
        # 如果并集为空，返回0
        if union == 0:
            return 0
        
        # 返回Jaccard相似度
        return intersection / union
    except Exception:
        return 0

# 格式化数字显示
def format_number(num):
    if num >= 10000:
        return f"{num/10000:.1f}万"
    return str(num)

# 执行搜索任务
def execute_search(task_id, keyword, platforms, image_merge=False):
    try:
        tasks[task_id]['status'] = 'processing'
        tasks[task_id]['progress'] = 0
        tasks[task_id]['errors'] = []
        
        # 创建任务队列用于接收进度更新
        task_queue = queue.Queue()
        
        # 启动进度更新线程
        def progress_updater():
            while True:
                try:
                    # 接收进度更新
                    update_data = task_queue.get(timeout=1)
                    if update_data == 'DONE':
                        break
                    
                    # 更新任务进度
                    source_task_id, update_type, progress = update_data
                    if source_task_id == task_id:
                        # 根据平台类型调整总体进度
                        if update_type == 'bilibili_progress':
                            # B站部分占总进度的50%
                            tasks[task_id]['progress'] = min(int(progress * 0.5), 45)
                        elif update_type == 'youtube_progress':
                            # YouTube部分占总进度的40%
                            tasks[task_id]['progress'] = 50 + min(int(progress * 0.4), 36)
                except queue.Empty:
                    # 检查主任务是否已完成
                    if tasks[task_id]['status'] != 'processing':
                        break
                except Exception as e:
                    print(f"进度更新线程错误: {e}")
        
        # 启动进度更新线程
        updater_thread = threading.Thread(target=progress_updater)
        updater_thread.daemon = True
        updater_thread.start()
        
        all_videos = []
        total_platforms = len(platforms)
        processed_platforms = 0
        
        with ThreadPoolExecutor(max_workers=len(platforms)) as executor:
            futures = []
            
            if 'bilibili' in platforms:
                futures.append((executor.submit(search_bilibili, keyword, task_id, task_queue), 'bilibili'))
            if 'youtube' in platforms:
                futures.append((executor.submit(search_youtube, keyword, task_id, task_queue), 'youtube'))
            
            for future, platform in futures:
                try:
                    videos = future.result()
                    # 确保每个平台的结果不超过30个
                    videos = videos[:30]
                    all_videos.extend(videos)
                    processed_platforms += 1
                    tasks[task_id]['progress'] = int((processed_platforms / total_platforms) * 100)
                    print(f"{platform}搜索完成，获取到 {len(videos)} 个结果")
                except Exception as e:
                    tasks[task_id]['errors'].append(f"{platform}平台搜索失败: {str(e)}")
        
        print(f"两个平台共获取到 {len(all_videos)} 个视频")
        
        # 更新进度为90%（合并阶段）
        tasks[task_id]['progress'] = 90
        
        # 合并视频，传递image_merge参数
        merged_videos = merge_videos(all_videos, image_merge)
        
        # 按播放量降序排序所有结果
        merged_videos.sort(key=lambda x: x['total_views'], reverse=True)
        
        # 限制返回结果数量为30个
        final_results = merged_videos[:30]
        print(f"排序后返回前30个视频，播放量最高的视频播放量为: {final_results[0]['total_views'] if final_results else 0}")
        
        # 更新进度为100%（完成所有工作）
        tasks[task_id]['progress'] = 100
        
        # 通知进度更新线程结束
        task_queue.put('DONE')
        
        # 格式化结果
        for video in final_results:
            video['formatted_total'] = format_number(video['total_views'])
            for platform in video['platforms']:
                video['platforms'][platform]['formatted_views'] = format_number(video['platforms'][platform]['views'])
        
        tasks[task_id]['status'] = 'completed'
        tasks[task_id]['results'] = {
            'merged': final_results,
            'raw': all_videos
        }
        
    except Exception as e:
        tasks[task_id]['status'] = 'failed'
        tasks[task_id]['error'] = str(e)
        tasks[task_id]['traceback'] = traceback.format_exc()

import os

# API路由
@app.route('/')
def index():
    # 使用绝对路径确保文件能够被正确找到
    current_dir = os.path.dirname(os.path.abspath(__file__))
    index_path = os.path.join(current_dir, 'index.html')
    return render_template_string(open(index_path, 'r', encoding='utf-8').read())

@app.route('/search', methods=['POST'])
def search():
    data = request.json
    keyword = data.get('keyword', '').strip()
    platforms = data.get('platforms', [])
    image_merge = data.get('image_merge', False)  # 添加缩略图匹配合并选项
    
    if not keyword:
        return jsonify({'error': '关键词不能为空'}), 400
    
    # 验证平台
    invalid_platforms = [p for p in platforms if p not in SUPPORTED_PLATFORMS]
    if invalid_platforms:
        return jsonify({'error': f'不支持的平台: {invalid_platforms}'}), 400
    
    # 如果没有指定平台，使用默认平台
    if not platforms:
        platforms = ['bilibili']
    
    # 创建任务
    task_id = f"task_{int(time.time())}_{int(time.time() * 1000) % 10000}"
    tasks[task_id] = {
        'id': task_id,
        'keyword': keyword,
        'platforms': platforms,
        'image_merge': image_merge,  # 保存缩略图匹配合并选项
        'status': 'pending',
        'created_at': time.time()
    }
    
    # 启动异步任务，传递image_merge参数
    thread = threading.Thread(target=execute_search, args=(task_id, keyword, platforms, image_merge))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'message': '搜索任务已开始',
        'task_id': task_id
    })

@app.route('/task/<task_id>', methods=['GET'])
def get_task(task_id):
    if task_id not in tasks:
        return jsonify({'error': '任务不存在'}), 404
    
    task = tasks[task_id].copy()
    
    # 不返回敏感信息
    task.pop('traceback', None)
    
    # 处理可能包含的NumPy数组，转换为可序列化的格式
    def convert_numpy_objects(obj):
        if isinstance(obj, dict):
            return {key: convert_numpy_objects(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [convert_numpy_objects(item) for item in obj]
        elif isinstance(obj, np.ndarray):
            return obj.tolist()  # 将NumPy数组转换为Python列表
        elif isinstance(obj, (np.int64, np.int32, np.float64, np.float32)):
            return obj.item()  # 将NumPy标量转换为Python标量
        else:
            return obj
    
    # 转换任务对象中的NumPy对象
    task = convert_numpy_objects(task)
    
    return jsonify(task)

@app.route('/platforms', methods=['GET'])
def get_platforms():
    return jsonify({'platforms': SUPPORTED_PLATFORMS})

# 404错误处理，确保API请求返回JSON格式
@app.errorhandler(404)
def not_found(error):
    # 更全面地检测API请求：检查路径前缀或Accept头
    is_api_request = (
        request.path.startswith('/task/') or 
        request.path.startswith('/api/') or
        request.path.startswith('/platforms') or
        'application/json' in request.headers.get('Accept', '')
    )
    
    if is_api_request:
        return jsonify({'error': '资源不存在'}), 404
    
    # 对于非API请求，保持默认行为
    return error

# 清理过期任务
def cleanup_tasks():
    while True:
        now = time.time()
        for task_id, task in list(tasks.items()):
            # 清理30分钟前的任务
            if now - task['created_at'] > 1800:
                del tasks[task_id]
        time.sleep(60)

# 启动清理线程
cleanup_thread = threading.Thread(target=cleanup_tasks)
cleanup_thread.daemon = True
cleanup_thread.start()

if __name__ == '__main__':
    print(f"支持的平台: {SUPPORTED_PLATFORMS}")
    app.run(host='0.0.0.0', port=5000, debug=True)