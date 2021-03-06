#encoding:utf-8
import time,datetime
import threading
from django.http import Http404
from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.shortcuts import render_to_response as render
from django.core.paginator import Paginator,InvalidPage,EmptyPage
from django.core.mail import send_mail
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.template import RequestContext
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_protect
from settings import *
from models import *
from main.verify.views import *
from forms import WikiForm
from signals import new_wiki_was_post
from image_downloader import ImageDownloader

#@cache_page(60*60)
def list(request,page=1):
    """
    列表页
    """
    current_page = APP
    nowtime = datetime.datetime.now()
    pre_url = APP
    allow_category = True
    category_name = str(request.GET.get('category','')) 
    tag_name = str(request.GET.get('tag',''))

    if category_name:
        suf_url = '?category=%s' %category_name
        try:
            category_obj = Category.objects.get(name=category_name)
        except Category.DoesNotExist:
            raise Http404()
        else:
            entry_all = Entry.objects.filter(public=True,sub_time__lt = nowtime,category=category_obj)
    elif tag_name:
        suf_url = '?tag=%s' %tag_name
        try:
            tag_obj = Tag.objects.get(name=tag_name)
        except Tag.DoesNotExist:
            raise Http404()
        else:
            entry_all = Entry.objects.filter(public=True,sub_time__lt = nowtime,tag=tag_obj)
    else:
        entry_all = Entry.objects.filter(public=True,sub_time__lt = nowtime)


    #按分页获取文章条目        
    paginator = Paginator(entry_all,20)

    try :
        entrys = paginator.page(page)
    except(InvalidPage,EmptyPage):
        entrys = paginator.page(paginator.num_pages)
    return render(LIST_PAGE,locals(),context_instance=RequestContext(request))

#@cache_page(60*60)
def tag(request,tag_name,page=1):
    """
    按标签显示条目
    """
    current_page = APP
    app = APP
    pre_url = 'wiki/tag/%s'%tag_name
    nowtime = datetime.datetime.now()
    
    try:
        tag = Tag.objects.get(name = tag_name)
    except Tag.DoesNotExist:
        raise Http404()
    
    entry_all = Entry.objects.filter(public=True,sub_time__lt = nowtime,tag=tag)
    paginator = Paginator(entry_all,20)
    
    try:
        entrys = paginator.page(page)
    except (EmptyPage,InvalidPage):
        entrys = paginator.page(paginator.num_pages)

    return render(LIST_PAGE,locals(),context_instance=RequestContext(request))

def detail(request,id):
    """
    浏览文章详细内容
    """
    template_name = 'wiki_cache_%s.html'%id
    try:
        id = int(id)
    except Exception:
        raise Http404()
    
    current_page = APP
    nowtime = datetime.datetime.now()
    next = '/wiki/%d/' %(int(id))
    
    try:
        entry = Entry.objects.get(id = id)
    except Entry.DoesNotExist:
        raise Http404()
    
    Entry.objects.filter(id = id).update(click_time = int(entry.click_time)+1) # 浏览次数加1
    return render(DETAIL_PAGE,locals(),context_instance=RequestContext(request))

@csrf_protect
def post(request):
    """
    匿名用户投稿
    """
    
    #########################################################################################
    # 用户操作行为安全保护

    # 计时器
    timer = time.time() - request.session.get('time_stamp',0)

    # 危险操作次数
    action_times = request.session.get('action_times',0)

    # 错误次数是否大于最大
    if action_times >= 1:
        if not check_verify(request):
            return render('verify.html',locals(),context_instance=RequestContext(request))
        else:

            # 重置标志位
            reset(request)

    elif timer > 60:
        # 重置标志位
        reset(request)
    #########################################################################################

    current_page = APP

    # 处理GET请求
    if request.method == 'GET':
        form = WikiForm()
        return render('wiki_post.html',locals(),context_instance=RequestContext(request))

    # 处理POST请求
    form = WikiForm(request.POST)
    set(request)
    if form.is_valid():
        data = form.cleaned_data
        try:
            send_mail(u'投稿',u'文章链接：%s' %data['source'],'wiki@pythoner.net',['admin@pythoner.net'])
        except Exception:
            pass
        msg = '感谢你的投稿，链接已发送至管理员'
        return render('posted.html',locals(),context_instance=RequestContext(request))
    else:
        return render('wiki_post.html',locals(),context_instance=RequestContext(request))

@login_required
@csrf_protect
def add(request):
    """ 用户写新的文章 """
    current_page = 'user_wiki'
    title = '写新笔记'

    # 处理GET请求
    if request.method == 'GET':
        form = WikiForm()
        return render('wiki_add.html',locals(),context_instance=RequestContext(request))

    # 处理POST请求
    form = WikiForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        new_wiki = Entry()
        new_wiki.author = request.user
        new_wiki.title = data['title']
        new_wiki.content = data['content']
        new_wiki.source = data['source'] and data['source'] or 'http://pythoner.net/home/%d/' %request.user.id
        
        try:
            new_wiki.save()
        except Exception,e:
            return HttpResponse('保存文章时出错：%s'%e)
        else:

            # 开启线程添加文章标签
            TagingThread(wiki_object=new_wiki).start()
            # 开启下载图片的线程
            ImageDownloader(new_wiki).start()
            # 发送信号
            new_wiki_was_post.send(
                sender= new_wiki.__class__,
                wiki =  new_wiki
            )
            return HttpResponseRedirect('/wiki/%d/' %new_wiki.id)
    else:
        return render('wiki_add.html',locals(),context_instance=RequestContext(request))

@login_required
@csrf_protect
def edit(request,wiki_id):
    """ 用户编辑文章 """
    current_page = 'user_wiki'
    title = '修改文章'

    try:
        wiki_id = int(wiki_id)
    except ValueError:
        raise Http404()
    
    try:
        wiki = Entry.objects.get(id=wiki_id,author=request.user)
    except Entry.DoesNotExist:
        raise Http404()
    
    # 处理GET请求
    if request.method == 'GET':
        form = WikiForm(instance=wiki)
        return render('wiki_add.html',locals(),context_instance=RequestContext(request))

    # 处理POST请求    
    form = WikiForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        wiki.title = data['title']
        wiki.content = data['content']
        wiki.source = data['source'] and data['source'] or 'http://pythoner.net/home/%d/' %request.user.id
        try:
            wiki.save()
        except Exception,e:
            messages.error(request,'保存文章时出错：%s'%e)
            return HttpResponseRedirect('/home/wiki/')
        else:
            messages.success(request,'修改成功！')

        # 开启添加标签线程
        TagingThread(wiki_object=wiki).start()
        ImageDownloader(wiki).start()

        return HttpResponseRedirect('/wiki/%d/' %wiki.id)
    else:
        return render('wiki_add.html',locals(),context_instance=RequestContext(request))

@login_required
def delete(request,wiki_id):
    """
    用户删除文章
    """
    try:
        wiki = Entry.objects.get(id=wiki_id,author=request.user)
    except Entry.DoesNotExist:
        raise Http404()
    if request.user == wiki.author:
        wiki.delete()
        # 删除后回到用户文章列表
        return HttpResponseRedirect('/home/%d/wiki/'%request.user.id)
    else:
        return HttpResponse('非法操作！')

def auto_get_tags(request):
    """
    为某一篇文章添加标签
    """
    if request.user.id <> 1:
        return HttpResponse('please login')
    result = ''
    entrys = Entry.objects.all()
    for entry in entrys:
        entry.tag.clear()
        content = u'%s%s' %(entry.title,entry.content)
        for tag in Tag.objects.all():
            if content.lower().count(tag.name.lower())>0:
                entry.tag.add(tag)
        entry.save()

    return render('wiki_robot.html',locals())

class TagingThread(threading.Thread):
    """
    为文章添加标签线程
    """
    def __init__(self,wiki_object):
        self.wiki = wiki_object
        threading.Thread.__init__(self)

    def run(self):
        # 清除已有标签
        self.wiki.tag.clear()

        content = str(self.wiki.title) + self.wiki.content
        for tag in Tag.objects.all():
            if content.lower().count(tag.name.lower()) > 0:
                self.wiki.tag.add(tag)

        self.wiki.save()

    def test(self):
        try:
            self.run()
        except Exception,e:
            return e
        else:
            return 'OK'
