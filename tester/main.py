from loguru import logger
from flask import Flask, render_template, send_from_directory
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
	ROUND(AVG(download), 2) AS avg_download,
	ROUND(AVG(upload), 2) AS avg_upload,
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
 
 
TEMPLATE_QUERY_GRAPHS = """SELECT
        download,
        upload,
        ping
    FROM
        results
    WHERE
        created_at <= NOW()
        AND created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
    ORDER BY
        created_at;
"""


TEMPLATE_SVG_GRAPHS = """
<svg viewBox="0 0 300 100" preserveAspectRatio="none" opacity="0.5" class="chart" role="img" xmlns="http://www.w3.org/2000/svg" xmlns:svg="http://www.w3.org/2000/svg">
  <polyline
     fill="none"
     stroke="#STROKE_COLOUR_DOWNLOAD#"
     stroke-width="0.5"
     points="#POINTS_DOWNLOAD#"/>
  <polyline
     fill="none"
     stroke="#STROKE_COLOUR_UPLOAD#"
     stroke-width="0.5"
     points="#POINTS_UPLOAD#"/>
  <polyline
     fill="none"
     stroke="#STROKE_COLOUR_PING#"
     stroke-width="0.5"
     points="#POINTS_PING#"/>
</svg>
"""


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
    

def regen_graphs():
    periods = [1, 3, 7, 30]
    results = {}
    for period in periods:
        connection = get_connection()
        with connection:
            with connection.cursor() as cursor:
                cursor.execute(TEMPLATE_QUERY_GRAPHS, (period))
                result = cursor.fetchall()
                results[period] = result
                
    # Now that we have all data, let's generate some graphs!
    for period in periods:
        gen_period_graphs(period, results[period])
            
            
def gen_period_graphs(period, points):
    filename = f"graphs/{period}.svg"
    
    # Rebasing points with little padding on bottom and top
    # TODO: remapping points for prettier view
    
    maxest = max(max([_['ping'] for _ in points]), max([_['upload'] for _ in points]), max([_['download'] for _ in points]))
    
    rendered_points_download = ""
    for i in range(0, len(points)):
        x = 300 / len(points) * i
        y =  100 - (90 * (points[i]["download"] / maxest))
        p = f"{x} {y}\n"
        rendered_points_download += p
        
    rendered_points_upload = ""
    for i in range(0, len(points)):
        x = 300 / len(points) * i
        y =  100 - (90 * (points[i]["upload"] / maxest))
        p = f"{x} {y}\n"
        rendered_points_upload += p
        
    rendered_points_ping = ""
    for i in range(0, len(points)):
        x = 300 / len(points) * i
        y =  100 - (90 * (points[i]["ping"] / maxest))
        p = f"{x} {y}\n"
        rendered_points_ping += p
        
    
    with open(filename, "w") as output_file:
        output_file.write(
            TEMPLATE_SVG_GRAPHS\
                .replace("#STROKE_COLOUR_DOWNLOAD#", get_prop_colour("download"))\
                .replace("#STROKE_COLOUR_UPLOAD#", get_prop_colour("upload"))\
                .replace("#STROKE_COLOUR_PING#", get_prop_colour("ping"))\
                .replace("#POINTS_DOWNLOAD#", rendered_points_download)\
                .replace("#POINTS_UPLOAD#", rendered_points_upload)\
                .replace("#POINTS_PING#", rendered_points_ping)
        )
        logger.info(f"Generated {filename}")
        
        
def get_prop_colour(prop):
    if prop == "download":
        return "#ff0000"
    if prop == "upload":
        return "#00ff00"
    if prop == "ping":
        return "#0000ff"
    return "#000000"
    


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
            logger.info("Trying to gather results...")
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
                        results_dict['upload'] / 1024 / 1024,
                        results_dict['download'] / 1024 / 1024,
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
            time.sleep(60)
        except Exception as e:
            logger.error(str(e))
            logger.warning("Waiting 10 seconds before restarting operations...")
            time.sleep(10)
            
    logger.info("Exiting...")


@app.route('/', methods=['GET'])
def root():
    regen_graphs()
    return render_template('index.html', stats=get_all_stats())


@app.route('/graphs/<path:path>')
def graphs(path):
    return send_from_directory('graphs', path)


if __name__ == "__main__":
    t = threading.Thread(target=tester_worker, args=())
    t.start()

    app.run(host="0.0.0.0", port="5000")
