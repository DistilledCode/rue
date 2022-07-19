import datetime
import logging

from utils import DB_SOURCE, MAX_LOGS, load_db

__all__ = ["logger"]


class DBLogHandler(logging.Handler):
    def __init__(self) -> None:
        logging.Handler.__init__(self)
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS 
                        log(
                            timestamp TIMESTAMP NOT NULL,
                            level TEXT NOT NULL,
                            filename TEXT NOT NULL,
                            funcname TEXT NOT NULL,
                            id TEXT,
                            message TEXT NOT NULL,
                            isexception BOOL NOT NULL,
                            traceback TEXT,
                            stackinfo TEXT
                            );
                        """
            )
        self._update_record_num()

    def handleError(self, record: logging.LogRecord) -> None:
        return super().handleError(record)

    def emit(self, record: logging.LogRecord) -> None:
        self.format(record=record)
        if record.exc_info is not None:
            is_exception = True
            exc_traceback = "".join(i for i in record.exc_text)
        else:
            is_exception = False
            exc_traceback = None

        obj_id = getattr(record, "id", None)
        try:
            time_stamp = datetime.datetime.fromtimestamp(record.created)
            record_vals = (
                time_stamp,
                record.levelname,
                f"{record.filename}:{record.lineno}",
                record.funcName,
                obj_id,
                record.message,
                is_exception,
                exc_traceback,
                record.stack_info,
            )
        except Exception:
            self.handleError(record)
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """INSERT INTO log
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s);
                """,
                record_vals,
            )
        self.record_num += 1
        while self.record_num > MAX_LOGS:
            self._bisect()

    def _update_record_num(self):
        with load_db(**DB_SOURCE) as cur:
            cur.execute("SELECT COUNT(*) FROM log;")
            self.record_num = cur.fetchall()[0][0]

    def _bisect(self):
        with load_db(**DB_SOURCE) as cur:
            cur.execute(
                """DELETE FROM log
                    WHERE timestamp IN (
                        SELECT timestamp
                        FROM log
                        ORDER BY timestamp
                        LIMIT (
                            SELECT COUNT(*)
                            FROM log
                        )/2
                    );
                """
            )
        self._update_record_num()
        # + 1 for this very record itself
        logger.debug(f"Bisected {self.__class__} to lenght {self.record_num + 1}")


def _get_logger():
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    frmt = "{asctime} {levelname:^10} {filename}:{lineno}  {message}"
    formatter = logging.Formatter(frmt, style="{")
    db_handler = DBLogHandler()
    db_handler.setFormatter(formatter)
    db_handler.setLevel(logging.DEBUG)
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    logger.addHandler(db_handler)
    return logger


logger = _get_logger()
