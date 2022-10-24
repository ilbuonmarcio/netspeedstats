from loguru import logger
from flask import Flask, render_template
import threading
import speedtest
import pymysql
import time
import json
import sys
import os


app = Flask(__name__)
app.config.update(
    TESTING=False,
    ENV='production',
    DEBUG=False
)


servers = []
threads = 4


# The parameter here is for days between TODAY and TODAY - %s DAYS
TEMPLATE_QUERY_REPORT = """SELECT
	ROUND(AVG(download) / 1024 / 1024 * 8, 2) AS avg_download,
	ROUND(AVG(upload) / 1024 / 1024 * 8, 2) AS avg_upload,
	ROUND(AVG(ping), 2) AS avg_ping,
	(
	SELECT
		CONCAT('(', server_id, ') ', server_name)
	FROM
		results
	WHERE
		created_at <= NOW()
		AND created_at >= DATE_SUB(NOW(), INTERVAL 1 DAY)
	GROUP BY
		server_id
	ORDER BY
		COUNT(server_id) DESC
	LIMIT 1) AS most_used_server,
	ROUND(LEAST(COUNT(*) / (24 * %s) * 100, 100), 2) AS period_coverage_percentage
FROM
	results
WHERE
	created_at <= NOW()
	AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY);"""


def get_stats(days=1):
    connection = get_connection()
    with connection:
        with connection.cursor() as cursor:
            cursor.execute(TEMPLATE_QUERY_REPORT, (days, days))
            result = cursor.fetchone()
            return result


def get_all_stats():
    return {
        1: get_stats(1),
        3: get_stats(3),
        7: get_stats(7),
        30: get_stats(30)
    }


def get_connection():
    return pymysql.connect(host=os.getenv('APP_DB_HOST'),
                                user=os.getenv('APP_DB_USER'),
                                password=os.getenv('APP_DB_PASS'),
                                database=os.getenv('APP_DB_NAME'),
                                cursorclass=pymysql.cursors.DictCursor)


def tester_worker():
    logger.info("Tester thread is running!")

    while True:
        try:
            s = speedtest.Speedtest()
            s.get_best_server()
            s.download(threads=threads)
            s.upload(threads=threads)

            results_dict = s.results.dict()

            connection = get_connection()
            with connection:
                with connection.cursor() as cursor:
                    sql = "INSERT INTO `results` (`upload`, `download`, `ping`, `server_id`, `server_name`, `client_ip`, `created_at`) VALUES (%s, %s, %s, %s, %s, %s, NOW())"
                    cursor.execute(sql, (
                        results_dict['upload'],
                        results_dict['download'],
                        results_dict['ping'],
                        results_dict['server']['id'],
                        results_dict['server']['sponsor'],
                        results_dict['client']['ip']))

                connection.commit()


            stats = get_all_stats()

            logger.info('-' * 64)
            logger.info(f"(Today) Period Coverage: {stats[1]['period_coverage_percentage']} % -> DL {stats[1]['avg_download']} Mbps, UL {stats[1]['avg_upload']} Mbps, PING {stats[1]['avg_ping']}ms [most used server: {stats[1]['most_used_server']}]")
            logger.info(f"(Last 3 days) Period Coverage: {stats[3]['period_coverage_percentage']} % -> DL {stats[3]['avg_download']} Mbps, UL {stats[3]['avg_upload']} Mbps, PING {stats[3]['avg_ping']}ms [most used server: {stats[3]['most_used_server']}]")
            logger.info(f"(Last 7 days) Period Coverage: {stats[7]['period_coverage_percentage']} % -> DL {stats[7]['avg_download']} Mbps, UL {stats[7]['avg_upload']} Mbps, PING {stats[7]['avg_ping']}ms [most used server: {stats[7]['most_used_server']}]")
            logger.info(f"(Last 30 days) Period Coverage: {stats[30]['period_coverage_percentage']} % -> DL {stats[30]['avg_download']} Mbps, UL {stats[30]['avg_upload']} Mbps, PING {stats[30]['avg_ping']}ms [most used server: {stats[30]['most_used_server']}]")

            # Run every 1 hour
            time.sleep(3600)
        except:
            sys.exit(-1) # Restarts the container automagically!


@app.route('/', methods=['GET'])
def root():
    return render_template('index.html', stats=get_all_stats())


if __name__ == "__main__":
    t = threading.Thread(target=tester_worker, args=())
    t.start()

    app.run(host="0.0.0.0", port="5000")