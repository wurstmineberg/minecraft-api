#!/usr/bin/env python3

import sys

sys.path.append('/opt/py')

import bottle

import api.util
import api.v1
import api.v2

from api.version import __version__

application = api.util.Bottle()

application.merge(api.v1.application)

application.mount('/v2/', api.v2.application)

if __name__ == '__main__':
    bottle.run(app=application, host='0.0.0.0', port=8081)
