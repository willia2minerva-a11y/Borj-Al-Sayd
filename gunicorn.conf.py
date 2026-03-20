# gunicorn.conf.py
import multiprocessing

bind = "0.0.0.0:10000"
workers = 2          # عدد العمال (يُفضل 2-4 حسب الخطة)
threads = 2          # عدد الخيوط لكل عامل
timeout = 120        # مهلة الطلب
graceful_timeout = 30
keepalive = 5
accesslog = "-"
errorlog = "-"
