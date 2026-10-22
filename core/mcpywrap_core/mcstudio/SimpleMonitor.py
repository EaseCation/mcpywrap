# -*- coding: utf-8 -*-


class SimpleMonitor:
    def __init__(self, process_name="Minecraft.Windows.exe"):
        self.process_name = process_name
        self.running = False

        # 检查进程是否已启动
        import psutil
        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == self.process_name:
                self.running = True
                break

    def wait(self):
        """等待进程结束"""
        import psutil
        import time

        # 等待游戏启动
        start_time = time.time()
        while not self.running and time.time() - start_time < 30:
            for proc in psutil.process_iter(['name']):
                if proc.info['name'] == self.process_name:
                    self.running = True
                    break
            time.sleep(1)

        # 如果游戏已启动，等待它结束
        if self.running:
            while True:
                found = False
                for proc in psutil.process_iter(['name']):
                    if proc.info['name'] == self.process_name:
                        found = True
                        break
                if not found:
                    break
                time.sleep(1)

        return True
    
    def poll(self):
        """检查进程是否仍在运行"""
        import psutil

        for proc in psutil.process_iter(['name']):
            if proc.info['name'] == self.process_name:
                return True
        return False