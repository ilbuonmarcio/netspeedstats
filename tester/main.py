from loguru import logger
import speedtest
import pymysql
import time
import json
import os


def get_connection():
    return pymysql.connect(host=os.getenv('APP_DB_HOST'),
                                user=os.getenv('APP_DB_USER'),
                                password=os.getenv('APP_DB_PASS'),
                                database=os.getenv('APP_DB_NAME'),
                                cursorclass=pymysql.cursors.DictCursor)

servers = []
threads = 4

while True:
    s = speedtest.Speedtest()
    s.get_best_server()
    s.download(threads=threads)
    s.upload(threads=threads)

    results_dict = s.results.dict()
    logger.info(results_dict)

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

    # Run every 1 hour
    time.sleep(3600)
