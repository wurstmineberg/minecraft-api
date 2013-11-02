#!/usr/bin/python
'''
A basic bottle app skeleton
'''

SERVERLOCATION="/opt/wurstmineberg/server/wurstmineberg"

DOCUMENTATION_INTRO="""
Welcome to the Wurstmineberg API. Feel free to play around!<br>
<br>
Currently available API endpoints:
"""

import os
import json
from bottle import *
from nbt import *

app = application = Bottle()

@app.route('/')
def show_index():
    '''
    The documentation page
    '''
    documentation = DOCUMENTATION_INTRO
    for route in app.routes:
        documentation += "<br>* " + route.rule + ": " + str(route.callback.__doc__)
    return documentation

def nbt_to_dict(nbtfile):
    dict = {}
    is_collection = False
    is_dict = False
    collection = []
    for tag in nbtfile.tags:
        if "tags" in tag.__dict__:
            if tag.name == "":
                collection.append(nbt_to_dict(tag))
                is_collection = True
            else:
                dict[tag.name] = nbt_to_dict(tag)
                is_dict = True
        else:
            if tag.name == "":
                collection.append(tag.value)
                is_collection = True
            else:
                dict[tag.name] = tag.value
                is_dict = True

    if is_dict and is_collection:
        dict["collection"] = collection
        return dict

    if is_collection:
        return collection
    else:
        return dict

@app.route('/player/:player_name/playerdata.json')
def api_player_data(player_name):
    '''
    Returns the player data encoded as JSON
    '''
    nbtfile = nbt.NBTFile(SERVERLOCATION + "/players/" + player_name + ".dat")

    return nbt_to_dict(nbtfile)

@app.route('/player/:player_name/stats.json')
def api_stats(player_name):
    '''
    Returns the stats JSON file from the server
    '''
    return static_file('/stats/' + player_name + '.json', SERVERLOCATION)

@app.route('/server/scoreboard.json')
def api_scoreboard():
    '''
    Returns the scoreboard data encoded as JSON
    '''
    nbtfile = nbt.NBTFile(SERVERLOCATION + "/data/scoreboard.dat")
    return nbt_to_dict(nbtfile)

@app.route('/server/level.json')
def api_level():
    '''
    Returns the level.dat encoded as JSON
    '''
    nbtfile = nbt.NBTFile(SERVERLOCATION + "/level.dat")
    return nbt_to_dict(nbtfile)

@app.route('/server/playerstats.json')
def api_playerstats():
    '''
    Returns all player stats in one file. This file can be potentially big. Please use one of the other APIs if possible.
    '''
    data = {}
    directory = os.path.join(SERVERLOCATION, 'stats')
    for root,dirs,files in os.walk(directory):
        for file in files:
            if file.endswith(".json"):
                with open(os.path.join(directory, file), 'r') as playerfile:
                    name = os.path.splitext(file)[0]
                    data[name] = json.loads(playerfile.read())
    return data

@app.route('/server/playerstats/general.json')
def api_playerstats_general():
    '''
    Returns all general stats in one file
    '''
    alldata = api_playerstats()
    data = {}
    nonGeneralActions = ['useItem', 'craftItem', 'breakItem', 'mineBlock']

    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        for statstr in playerdata:
            value = playerdata[statstr]
            stat = statstr.split('.')
            if stat[0] == 'stat' and stat[1] not in nonGeneralActions:
                    playerdict[statstr] = value
        data[player] = playerdict
    return data

@app.route('/server/playerstats/item.json')
def api_playerstats_items():
    '''
    Returns all item and block stats in one file
    '''
    alldata = api_playerstats()
    data = {}
    itemActions = ['useItem', 'craftItem', 'breakItem', 'mineBlock']

    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        for statstr in playerdata:
            value = playerdata[statstr]
            stat = statstr.split('.')
            if stat[0] == 'stat' and stat[1] in itemActions:
                playerdict[statstr] = value
        data[player] = playerdict
    return data                                                                                                                                      

@app.route('/server/playerstats/achievement.json')
def api_playerstats_achievements():
    '''
    Returns all achievement stats in one file
    '''
    alldata = api_playerstats()
    data = {}

    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        for statstr in playerdata:
            value = playerdata[statstr]
            stat = statstr.split('.')
            if stat[0] == 'achievement':
                playerdict[statstr] = value
        data[player] = playerdict
    return data

@app.route('/server/playerstats/by-id/:identifier')
def api_playerstats_by_id(identifier):
    '''
    Returns the stat item :identifier from all player stats
    '''
    alldata = api_playerstats()

    data = {}
    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        if identifier in playerdata:
            data[player] = playerdata[identifier]
    if len(data) == 0:
        abort(404, "Identifier not found")
    return data

class StripPathMiddleware(object):
    '''
    Get that slash out of the request
    '''
    def __init__(self, a):
        self.a = a
    def __call__(self, e, h):
        e['PATH_INFO'] = e['PATH_INFO'].rstrip('/')
        return self.a(e, h)

if __name__ == '__main__':
    run(app=StripPathMiddleware(app),
        server='python_server',
        host='0.0.0.0',
        port=8080)

