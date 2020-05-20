from urllib import parse
import random
import re
import copy
import time
import os

from requests_toolbelt.multipart.encoder import MultipartEncoder
from lxml import etree
import requests


class LanZou:
    def __init__(self, PHPSESSID="", phpdisk_info="", ylogin=""):
        """
        假如仅仅是想获取文件的话，不需要传cookie
        :param PHPSESSID: cookie
        :param phpdisk_info: cookie
        :param ylogin: cookie
        """
        self._cookies = {
            "PHPSESSID": PHPSESSID,
            "phpdisk_info": phpdisk_info,
            "ylogin": ylogin
        }
        self._headers = {
            "Accept": "* / *",
            "Accept - Encoding": "gzip, deflate, br",
            'Accept-Language': 'zh-CN,zh;q=0.9',  # 提取直连必需设置这个，否则拿不到数据
            "DNT": "1",
            "Origin": "https://up.woozooo.com",
            "Referer": "https://up.woozooo.com/mydisk.php?item=files&action=index",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/75.0.3770.100 Safari/537.36"
        }
        # 允许上传的列表
        self._allow_up_type_list = ['doc', 'docx', 'zip', 'rar', 'apk', 'ipa', 'txt', 'exe', '7z', 'e', 'z', 'ct', 'ke',
                                    'cetrainer', 'db', 'tar', 'pdf', 'w3x', 'epub', 'mobi', 'azw', 'azw3', 'osk', 'osz',
                                    'xpa', 'cpk', 'lua', 'jar', 'dmg', 'ppt', 'pptx', 'xls', 'xlsx', 'mp3', 'ipa',
                                    'iso', 'img', 'gho', 'ttf', 'ttc', 'txf', 'dwg', 'bat', 'imazingapp', 'dll', 'crx',
                                    'xapk', 'conf', 'deb', 'rp', 'rpm', 'rplib', 'mobileconfig', 'appimage', 'lolgezi',
                                    'fla']
        # 上传文件url
        self._up_url = "http://pc.woozooo.com/fileup.php"
        # 很多操作都要使用这个url
        self._do_load_url = "https://pc.woozooo.com/doupload.php"
        # 下载时用到以下两个url
        self._dow_url = "https://lanzous.com/ajaxm.php"
        self._dow_dom = "https://vip.d0.baidupan.com/file/"
        # 显示更多 url
        self._file_more_url = "https://lanzous.com/filemoreajax.php"
        self._session = requests.session()
        self._dow_session = requests.session()
        self._disk_json = None

    def up(self, file_path: str, folder_id: str):
        """
        上传单个文件
        目前（2020年05月13日01:37:32）蓝奏云的上传规则：
            cookie中folder_id_c记录目前的id
            通过"WU_FILE_" + 一个数 作为id，实际上就是记录这一次（WU_FILE_1）和上一次（WU_FILE_0）的文件夹id

        :param file_path: 文件所在目录，建议绝对路径
        :param folder_id: 上传到文件夹的id
        :return: {"status": 1, "msg": "success"}
        status:
            0 ==> 失败，蓝奏云返回造成的
            1 ==> 成功
            2 ==> 失败，用户的问题
        """
        file_path = file_path.replace("\\", "/")
        ret = {"status": 1, "msg": "success"}
        if not os.path.isfile(file_path):
            # 不是文件
            ret["status"] = 2
            ret["msg"] = "%s 不是一个文件" % file_path
            return ret
        filename = file_path.split("/")[-1]
        file_type = filename.split(".")[-1]
        if file_type not in self._allow_up_type_list:
            ret["status"] = 2
            ret["msg"] = "不能上传的文件格式：%s" % file_type
            return ret
        # 编码中文
        filename = parse.quote(filename)
        size = os.stat(file_path).st_size
        if not size:
            # 空文件时不能上传
            ret["status"] = 2
            ret["msg"] = "不能上传空文件：%s" % file_path
            return ret
        # 制作上传的数据 multipart/form-data
        multipart_encoder = MultipartEncoder(
            fields={
                "task": "1",
                "folder_id": "-1",
                "ve": "1",
                "id": "WU_FILE_1",
                "name": filename,
                "type": "application/octet-stream",
                # "size": str(size),
                'upload_file': (filename, open(file_path, 'rb'), 'application/octet-stream')
            },
            boundary='-----------------------------' + str(random.randint(1e28, 1e29 - 1))
        )
        # 修改cookie
        new_cookie = copy.deepcopy(self._cookies)
        new_cookie["folder_id_c"] = folder_id
        self._headers["Content-Type"] = multipart_encoder.content_type
        up_res_json = self._session.post(url=self._up_url, data=multipart_encoder, headers=self._headers,
                                         cookies=new_cookie).json()
        if up_res_json.get('zt') != 1:
            ret["status"] = 0
            ret["msg"] = up_res_json.get("info")

        return ret

    def up_folder(self, folder_path: str, folder_id: str, iterate=False):
        """
        文件夹内所有文件上传
        :param folder_path: 文件夹路径
        :param folder_id: 要上传的那个文件夹的id
        :param iterate: 是否要连同子文件夹内的文件一并上传，注：蓝奏云不能创建超过4级目录
        :return: {"status": 1, "msg": "success", "note": []}
        status:
            0 ==> 失败
            1 ==> 成功
            2 ==> 有点问题，信息在note中
        """
        folder_path = folder_path.replace("\\", "/")
        if not folder_path.endswith("/"):
            folder_path += "/"
        ret = {"status": 1, "msg": "success", "note": []}
        if not os.path.isdir(folder_path):
            ret["status"] = 0
            ret["msg"] = "%s 不是一个文件夹" % folder_path

        file_list = os.listdir(folder_path)
        for f in file_list:
            f_path = folder_path + f
            # 操作文件
            if os.path.isfile(f_path):
                up_res = self.up(f_path, folder_id=folder_id)
                if up_res.get("status") == 0:
                    # 报错
                    ret["status"] = 0
                    ret["msg"] = up_res.get("msg")
                elif up_res.get("status") == 2:
                    ret["status"] = 2
                    ret["msg"] = "自己看看note吧"
                    ret["note"].append(up_res.get("msg"))
            # 处理文件夹
            elif os.path.isdir(f_path) and iterate:
                # TODO：完善
                # 选择上传迭代文件的话，连同子文件夹内的文件一并上传
                mk_res = self.mkdir(folder_id, f, "转换")
                if mk_res.get("status"):
                    f_id = mk_res.get("f_id")
                    # 递归全部文件夹
                    self.up_folder(f_path, f_id, iterate)
        return ret

    def disk(self, folder_id: str = "-1"):
        """
        获取文件列表
        :param folder_id: 获取获取信息的目录，默认根目录
        :return: {"status": 1, "msg": "success", "folder_data": [...], "file_data": [...]}
        """
        ret = {"status": 1, "msg": "success", "folder_data": [], "file_data": []}
        folder_ok = False
        file_ok = False

        folder_data = {
            "task": 47,
            "folder_id": folder_id,
            "pg": 1,
        }
        file_data = {
            "task": 5,
            "folder_id": folder_id,
            "pg": 1,
        }

        while True:
            if not folder_ok:
                folder_json = self._session.post(url=self._do_load_url, data=folder_data, headers=self._headers,
                                                 cookies=self._cookies).json()
                if not self._disk_info(folder_json, ret, folder_data, "folder"):
                    # 此时结束改请求
                    folder_ok = True
            if not file_ok:
                file_json = self._session.post(url=self._do_load_url, data=file_data, headers=self._headers,
                                               cookies=self._cookies).json()
                if not self._disk_info(file_json, ret, file_data, "file"):
                    file_ok = True
            if folder_ok and file_ok:
                return ret

    def _disk_info(self, f_json, ret, post_data, flag):
        # 返回True ==> 正常或请求过快
        # 返回False ==> 页面请求完了或报错了
        if f_json.get("zt") == 1 or f_json.get("zt") == 2:
            if f_json.get("text"):
                # 正常情况
                if flag == "file":
                    for data in f_json.get("text"):
                        temp = {"f_id": data.get("id"), "name": data.get("name_all"),
                                "size": data.get("size"), "time": data.get("time")}
                        ret["file_data"].append(temp)
                elif flag == "folder":
                    if self._disk_json == f_json:
                        return False
                    for data in f_json.get("text"):
                        temp = {"f_id": data.get("fol_id"), "name": data.get("name"),
                                "folder_des": data.get("folder_des")}
                        ret["folder_data"].append(temp)
                    # 蓝奏云的规则如此
                    # 请求文件夹时，即使页数超过范围了，还是这样返回，所以只能比对两次拿到的值
                    self._disk_json = f_json
                post_data["pg"] += 1  # 加一页
                return True
            else:
                return False

        else:
            ret["status"] = 0
            ret["msg"] = f_json.get("info")
            return False

    def mkdir(self, parent_id: str, folder_name: str, folder_description=""):
        """
        创建文件夹
        注：蓝奏云不能创建超过4级目录
        :param parent_id: 要往哪里创建文件夹的id， disk()方法获得的 文件夹id
        :param folder_name: 文件夹名字
        :param folder_description: 文件夹备注
        :return: {"status": 1, "msg": "success", "f_id": ""}  f_id是创建的文件夹id
        """
        ret = {"status": 1, "msg": "success", "f_id": ""}
        data = {
            "task": 2,
            "parent_id": parent_id,
            "folder_name": folder_name,
            "folder_description": folder_description
        }
        # 修改cookie
        new_cookie = copy.deepcopy(self._cookies)
        new_cookie["folder_id_c"] = parent_id
        res_json = self._session.post(url=self._do_load_url, data=data, headers=self._headers,
                                      cookies=new_cookie).json()
        if res_json.get("zt") != 1:
            ret["status"] = 0
            ret["msg"] = res_json.get("info")
        ret["f_id"] = res_json.get("text")
        return ret

    def file_share_url(self, file_id: str):
        """
        获取文件的分享url
        :param file_id:文件的id，根据disk方法获得
        :return:{"status": 1, "msg": "success", "pwd": "", "url": ""}
        """
        ret = {"status": 1, "msg": "success", "pwd": "", "url": ""}
        data = {
            "task": "22",
            "file_id": file_id
        }
        file_json = self._session.post(url=self._do_load_url, data=data, headers=self._headers,
                                       cookies=self._cookies).json()
        if file_json.get("zt") != 1:
            ret["status"] = 0
            ret["msg"] = file_json.get("text")
            return ret
        info = file_json.get("info")
        ret["pwd"] = info.get("pwd")
        ret["url"] = info.get("is_newd") + "/" + info.get("f_id")
        return ret

    def download_link(self, url):
        """
        获取没有密码的文件的中转下载链接，使用start_download()获取文件的字节内容
        获取下载链接个过程：
            1 请求文件所在url
            2 找到HTML中的 <div class="d"> => <div class="ifr"> => <iframe class="ifr2">中的src
            3 获取发送src中的请求，获取js的cots变量的值
            4 使用requests模拟发送，获取下载链接请求
            5 loads Json获取下载链接
        :param url: 文件的url
        :return: {"status": 1, "msg": "success", "download_link": ""}
        """
        # 1
        ret = {"status": 1, "msg": "success", "download_link": ""}
        r = self._dow_session.get(url=url, headers=self._headers)
        # 2
        html = etree.HTML(r.text)
        # <div class="d"> => <div class="ifr"> => <iframe class="ifr2">中的src
        src_list = html.xpath("""//div[@class='d2']/div[@class='ifr']/iframe[@class='ifr2']/@src""")
        if len(src_list) != 1:
            ret["status"] = 0
            ret["msg"] = "找不到src"
            return ret
        fn_url = "https://lanzous.com" + src_list[0]
        # 3
        fn_res = self._dow_session.get(fn_url).text
        fn_res_re = re.findall(r"var cots = '(.*)';//", fn_res)
        if len(fn_res_re) != 1:
            ret["status"] = 0
            ret["msg"] = "获取sign异常"
            return ret
        sign = fn_res_re[0]
        if sign == "st":
            # "st"这个结果是不行的，重新获取
            fn_res_re = re.findall(r"'sign':'(.*)','ves':1 },//", fn_res)
            sign = fn_res_re[0]
        # 4
        data = {"action": "downprocess",
                "sign": sign,
                "ves": 1
                }
        # 重新构造一个headers, 修改referer
        new_headers = copy.deepcopy(self._headers)
        new_headers["Referer"] = fn_url
        # 开始请求下载链接
        down_link_json = self._dow_session.post(self._dow_url, data=data, headers=new_headers).json()
        # 5
        if down_link_json.get("zt", 0) != 1:
            ret["status"] = 0
            ret["msg"] = down_link_json.get("inf")
            return ret
        down_link = self._dow_dom + down_link_json.get("url")
        ret["download_link"] = down_link
        return ret

    def download_link_pwd(self, url: str, password: str):
        """
        获取带密码文件的中转下载链接，使用start_download()获取文件的字节内容
        不带密码的文件请不要使用这个接口
        :param url: 文件链接
        :param password: 密码
        :return: {"status": 1, "msg": "success", "download_link": "..."}
        """
        ret = {"status": 1, "msg": "success", "download_link": ""}
        res = self._dow_session.get(url=url, headers=self._headers).text
        res_re = re.findall(r"&sign=(.*)&p='+", res)
        if len(res_re) != 1:
            ret["status"] = 0
            ret["msg"] = "没有匹配到sign"
            return ret
        sign = res_re[0]
        data = {"action": "downprocess",
                "sign": sign,
                "p": password}
        down_link_json = self._dow_session.post(url=self._dow_url, data=data, headers=self._headers).json()
        if down_link_json.get("zt") != 1:
            ret["status"] = 0
            ret["msg"] = down_link_json.get("inf")
            return ret
        down_link = self._dow_dom + down_link_json.get("url")
        ret["download_link"] = down_link
        return ret

    def download_folder_link(self, url: str, password=""):
        """
        获取文件夹中各个文件的中转下载链接，使用start_download()获取文件的字节内容

        :param url: 文件夹链接
        :param password: 密码，可选择，文件夹有密码时一定要输入密码
        :return: {"status": 1, "msg": "success", "data": [...]}
        """
        ret = {"status": 1, "msg": "success", "data": []}
        res = self._dow_session.get(url=url, headers=self._headers).text
        re_rule = r"""
			'lx':(?P<lx>.*),
			'fid':(?P<fid>.*),
			'uid':'(?P<uid>.*)',
			'pg':pgs,
			'rep':'0',
			't':(?P<t>.*),
			'k':(?P<k>.*),"""

        res_re = re.search(re_rule, res)
        res_re_t = re.findall(r"var %s = '(.*)'" % res_re.group("t"), res)
        res_re_k = re.findall(r"var %s = '(.*)'" % res_re.group("k"), res)

        data = {
            "lx": res_re.group("lx"),
            "fid": res_re.group("fid"),
            "uid": res_re.group("uid"),
            "pg": 1,
            "rep": 0,
            "t": res_re_t[0],
            "k": res_re_k[0],
            "up": 1,
            "ls": 1,
            "pwd": password
        }

        # 请求文件列表
        get_file_ret = self._dow_get_file_list(data)
        if not get_file_ret.get("status"):
            ret["status"] = 0
            ret["msg"] = get_file_ret.get("msg")
            return ret
        for one_page_file_json in get_file_ret.get("data"):
            for data_dic in one_page_file_json.get("text"):
                name = data_dic.get("name_all")
                url_id = data_dic.get("id")
                file_url = "https://lanzous.com/" + url_id
                dow_ret = self.download_link(file_url)
                if dow_ret.get("status"):
                    temp = {"file_name": name, "down_link": dow_ret.get("download_link")}
                    ret["data"].append(temp)
                else:
                    ret["status"] = 0
                    ret["msg"] = dow_ret.get("msg")
        return ret

    def _dow_get_file_list(self, data: dict, page=1):
        # 用于download_folder_link时 获取文件夹内全部文件
        ret = {"status": 1, "msg": "success", "data": []}
        while True:
            data["pg"] = page
            file_list_json = self._dow_session.post(url=self._file_more_url, data=data, headers=self._headers).json()
            if file_list_json.get("zt") == 1:
                # 正常情况
                ret["data"].append(file_list_json)
                page += 1
            elif file_list_json.get("zt") == 2:
                return ret
            elif file_list_json.get("zt") == 4:
                # 防止请求过快
                time.sleep(0.5)
            else:
                ret["status"] = 0
                ret["msg"] = file_list_json.get("info")
                return ret
            time.sleep(1)

    def start_download(self, down_link: str):
        """
        download_link / download_link_pwd / download_folder_link的中转链接是一个一个可以跳转的页面，
        不是真实下载连接，所以在这里获取下载的内容。
        注意：数据是字节类型
        :param down_link:中间跳转页面的url,在download_link / download_link_pwd / download_folder_link方法的返回值中
        :return:{"status": 1, "msg": "success", "data": b""}
        """
        ret = {"status": 1, "msg": "success", "data": b""}
        r = self._dow_session.get(down_link, headers=self._headers, cookies=self._cookies)
        r.encoding = r.apparent_encoding
        if r.status_code != 200:
            ret["status"] = 0
            ret["msg"] = "status code %s" % r.status_code
            return ret
        ret["data"] = r.content
        return ret

    def delete(self, f_type: str, f_id: str):
        """
        删除文件或 没有子文件夹 的文件夹
        :param f_type: 要删除的类型：file/folder (文件/文件夹)
        :param f_id: 删除的文件或文件夹对应的id
        :return:  {"status": 1, "msg": "success"}
        """
        ret = {"status": 1, "msg": "success"}
        if f_type == "file":
            data = {
                "task": "6",
                "file_id": f_id
            }
            pass
        elif f_type == "folder":
            data = {
                "task": "3",
                "folder_id": f_id
            }
        else:
            # 类型不对
            ret["status"] = 0
            ret["msg"] = "f_type为 'file'或'folder',而不是%s" % f_type
            return ret
        res_json = self._session.post(url=self._do_load_url, data=data, headers=self._headers,
                                      cookies=self._cookies).json()
        # 假如不成功
        if res_json.get("zt") != 1:
            ret["status"] = 0
            ret["msg"] = res_json.get("info")
        return ret