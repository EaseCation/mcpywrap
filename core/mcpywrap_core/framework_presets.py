"""框架预设数据。底层缓存、解析、事务和组装均不依赖本模块。"""
FRAMEWORK_PRESETS = {
    'qumod': {
        'title': 'QuMod', 'version': '1.4.3',
        'rev': 'a07430aaaa6dce5f1ef68de3fda52ea4b9366c2c',
        'sources': {'github': 'https://github.com/GitHub-Zero123/QuModLibs.git',
                    'gitee': 'https://gitee.com/bili_zero123/qu_mod_libs.git'},
        'default_source': 'github', 'kind': 'code',
        'subdir': 'Scripts/QuModLibs', 'folder': 'QuModLibs',
        'files': {
            '__init__.py': '# -*- coding: utf-8 -*-\n',
            'modMain.py': '# -*- coding: utf-8 -*-\n'
                          '# QMain 必须保留在入口命名空间，供网易加载器发现。\n'
                          'from .QuModLibs.QuMod import EasyMod, QMain\n\n'
                          'MOD = EasyMod()\nMOD.Server("Server")\nMOD.Client("Client")\n',
            **{side + '.py': '# -*- coding: utf-8 -*-\nfrom .QuModLibs.' + side + ' import Listen, DestroyFunc\n\n'
                '@Listen("OnScriptTick' + side + '")\ndef on_tick(args=None):\n    pass\n\n'
                '@DestroyFunc\ndef on_destroy():\n    pass\n\n'
                'print("[{script_dir}] ' + side.lower() + ' ready")\n' for side in ('Server', 'Client')},
        },
    },
}
