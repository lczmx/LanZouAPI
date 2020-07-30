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
            "ylogin": ylogin,
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
        # api
        self._parse_api = "http://v1.alapi.cn/api/lanzou"
        self._session = requests.session()
        self._dow_session = requests.session()
        self._work_count = 0  # 记录第几次上传了, 更新路径时会归零
        self._folder_id_c = "-1"  # 当前王家夹id
        self._disk_folder_json = None

    def up(self, file_path: str, folder_id: str):
        """
        上传单个文件
        目前（2020年05月13日01:37:32）蓝奏云的上传规则：
            cookie中folder_id_c记录目前的id
            通过"WU_FILE_" + 一个数 作为id，上传时用到

        :param file_path: 文件所在目录，建议绝对路径
        :param folder_id: 上传到文件夹的id
        :return: {"status": 1, "msg": "success", "f_id"}
        status:
            0 ==> 失败，蓝奏云返回造成的
            1 ==> 成功
            2 ==> 失败，用户的问题
        """
        file_path = file_path.replace("\\", "/")
        ret = {"status": 1, "msg": "success", "f_id": None}
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
                "id": "WU_FILE_%s" % self._work_count,
                "name": filename,
                "type": "application/octet-stream",
                # "size": str(size),
                'upload_file': (filename, open(file_path, 'rb'), 'application/octet-stream')
            },
            boundary='-----------------------------' + str(random.randint(1e28, 1e29 - 1))
        )
        # 修改cookie
        self._change_folder_id(folder_id)
        self._headers["Content-Type"] = multipart_encoder.content_type
        up_res_json = self._session.post(url=self._up_url, data=multipart_encoder, headers=self._headers,
                                         cookies=self._cookies).json()
        if up_res_json.get('zt') != 1:
            ret["status"] = 0
            ret["msg"] = up_res_json.get("info")
        # 获取f_id
        ret["f_id"] = up_res_json.get("text")[0].get("id")
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
                # 写入cookie中
                self._cookies["folder_id_c"] = folder_id
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
                    # 蓝奏云的规则如此
                    # 请求文件夹时，即使页数超过范围了，还是这样返回，所以只能比对两次拿到的值
                    if self._disk_folder_json == f_json:
                        self._disk_folder_json = None  # 清空
                        return False
                    self._disk_folder_json = f_json
                    for data in f_json.get("text"):
                        temp = {"f_id": data.get("fol_id"), "name": data.get("name"),
                                "folder_des": data.get("folder_des")}
                        ret["folder_data"].append(temp)

                post_data["pg"] += 1  # 加一页
                return True
            else:
                return False

        else:
            ret["status"] = 0
            ret["msg"] = f_json.get("info")
            return False

    def _change_folder_id(self, folder_id):
        if self._folder_id_c != folder_id:
            # 改变当前folder_id
            self.disk(folder_id)

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
        self._change_folder_id(parent_id)
        res_json = self._session.post(url=self._do_load_url, data=data, headers=self._headers,
                                      cookies=self._cookies).json()
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
        # {"zt":1,"info":{"pwd":"4q6q","onof":"0","f_id":"icxxeqd","taoc":"","is_newd":"https:\/\/wwa.lanzous.com"},"text":null}
        # {"zt":1,"info":{"pwd":"8gwx","onof":"1","f_id":"iy0n6drueed","taoc":"","is_newd":"https:\/\/wwa.lanzous.com"},"text":null}
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
        if info.get("onof") == "1":
            ret["pwd"] = info.get("pwd")
        ret["url"] = info.get("is_newd") + "/" + info.get("f_id")
        return ret

    def download_link(self, url, pwd=""):
        """
        获取文件或文件夹的直链，有密码的需要输入密码
        调用的是第三方API
        :param url: 文件或文件夹的分享链接
        :param pwd: 文件或文件夹的密码，无时留空
        :return: {"status": 1, "msg": "success", "download_link": "", "is_folder": False}
        """
        ret = {"status": 1, "msg": "success", "download_link": "", "pwd": "", "is_folder": False}
        res = self._accept_api_url(url, pwd)
        if res.get("code") != 200:
            ret["status"] = 0
            ret["msg"] = res.get("msg")
            return ret
        # 判断是否为文件夹
        data = res.get("data")
        if isinstance(data, list):
            ret["download_link"] = []
            ret["is_folder"] = True
            for i in data:
                if i.get("url") == "已超时，请刷新":
                    i["url"] = "文件设置了密码，无法获取直链"
                ret["download_link"].append(i)

        else:
            ret["download_link"] = data.get("url")

        return ret

    def _accept_api_url(self, url, pwd):
        if pwd:
            url = self._parse_api + "?url=%s&pwd=%s&format=json" % (url, pwd)
        else:
            url = self._parse_api + "?url=%s&format=json" % url
        res = self._dow_session.get(url).json()
        return res

    def download(self, url: str, pwd=""):
        """
        直接下载文件，注意不能是文件夹
        调用的是第三方API
        注意：数据是字节类型
        :param url: 文件的分享链接
        :param pwd: 文件或文件夹的密码，无时留空
        :return:{"status": 1, "msg": "success", "data": b""}
        """

        ret = {"status": 1, "msg": "success", "data": b""}
        res = self.download_link(url, pwd)
        if res.get("status") and not res.get("is_folder"):
            r = self._dow_session.get(url=res.get("download_link"), headers=self._headers)
            ret["data"] = r.content
            return ret
        ret["status"] = 0
        ret["msg"] = res.get("msg")
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
