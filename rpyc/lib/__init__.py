"""
A library of various helpers functions and classes
"""
import sys
import socket
import logging
import threading
import time
import random
from rpyc.lib.compat import maxint  # noqa: F401


class MissingModule(object):
    __slots__ = ["__name"]

    def __init__(self, name):
        self.__name = name

    def __getattr__(self, name):
        if name.startswith("__"):  # issue 71
            raise AttributeError("module %r not found" % (self.__name,))
        raise ImportError("module %r not found" % (self.__name,))

    def __bool__(self):
        return False
    __nonzero__ = __bool__


def safe_import(name):
    try:
        mod = __import__(name, None, None, "*")
    except ImportError:
        mod = MissingModule(name)
    except Exception:
        # issue 72: IronPython on Mono
        if sys.platform == "cli" and name == "signal":  # os.name == "posix":
            mod = MissingModule(name)
        else:
            raise
    return mod


def setup_logger(quiet=False, logfile=None):
    opts = {}
    if quiet:
        opts['level'] = logging.ERROR
    else:
        opts['level'] = logging.DEBUG
    if logfile:
        opts['filename'] = logfile
    logging.basicConfig(**opts)


class hybridmethod(object):
    """Decorator for hybrid instance/class methods that will act like a normal
    method if accessed via an instance, but act like classmethod if accessed
    via the class."""

    def __init__(self, func):
        self.func = func

    def __get__(self, obj, cls):
        return self.func.__get__(cls if obj is None else obj, obj)

    def __set__(self, obj, val):
        raise AttributeError("Cannot overwrite method")


def spawn(*args, **kwargs):
    """Start and return daemon thread. ``spawn(func, *args, **kwargs)``."""
    func, args = args[0], args[1:]
    thread = threading.Thread(target=func, args=args, kwargs=kwargs)
    thread.daemon = True
    thread.start()
    return thread


def spawn_waitready(init, main):
    """
    Start a thread that runs ``init`` and then ``main``. Wait for ``init`` to
    be finished before returning.

    Returns a tuple ``(thread, init_result)``.
    """
    event = threading.Event()
    stack = [event]     # used to exchange arguments with thread, so `event`
    # can be deleted when it has fulfilled its purpose.

    def start():
        stack.append(init())
        stack.pop(0).set()
        return main()
    thread = spawn(start)
    event.wait()
    return thread, stack.pop()


class Timeout:

    def __init__(self, timeout):
        if isinstance(timeout, Timeout):
            self.finite = timeout.finite
            self.tmax = timeout.tmax
        else:
            self.finite = timeout is not None and timeout >= 0
            self.tmax = time.time() + timeout if self.finite else None

    def expired(self):
        return self.finite and time.time() >= self.tmax

    def timeleft(self):
        return max((0, self.tmax - time.time())) if self.finite else None

    def sleep(self, interval):
        time.sleep(min(interval, self.timeleft()) if self.finite else interval)


def socket_backoff_connect(family, socktype, proto, addr, timeout, attempts):
    """connect will backoff if the response is not ready for a pseudo random number greater than zero and less than
        51e-6, 153e-6, 358e-6, 768e-6, 1587e-6, 3225e-6, 6502e-6, 13056e-6, 26163e-6, 52377e-6
    this should help avoid congestion.
    """
    sock = socket.socket(family, socktype, proto)
    collision = 0
    connecting = True
    while connecting:
        collision += 1
        try:
            sock.settimeout(timeout)
            sock.connect(addr)
            connecting = False
        except socket.timeout:
            if collision == attempts or attempts < 1:
                raise
            else:
                sock.close()
                sock = socket.socket(family, socktype, proto)
                time.sleep(exp_backoff(collision))
    return sock


def exp_backoff(collision):
    """ Exponential backoff algorithm from
    Peterson, L.L., and Davie, B.S. Computer Networks: a systems approach. 5th ed. pp. 127
    """
    n = min(collision, 10)
    supremum_adjustment = 1 if n > 3 else 0
    k = random.uniform(0, 2**n - supremum_adjustment)
    return k * 0.0000512
