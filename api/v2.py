import sys

sys.path.append('/opt/py')

import bottle
import collections
import contextlib
from datetime import datetime
import io
import json
import minecraft
import nbt.nbt
import os
import os.path
import pathlib
import re
import subprocess
import tempfile
import time
import uuid
import xml.sax.saxutils

import api.util
import api.util2

def parse_version_string():
    path = pathlib.Path(__file__).resolve().parent.parent # go up 2 levels, from repo/api/v2.py to repo, where README.md is located
    try:
        version = subprocess.check_output(['git', 'rev-parse', '--abbrev-ref', 'HEAD'], cwd=str(path)).decode('utf-8').strip('\n')
        if version == 'master':
            try:
                with (path / 'README.md').open() as readme:
                    for line in readme.read().splitlines():
                        if line.startswith('This is version '):
                            return line.split(' ')[3]
            except:
                pass
        return subprocess.check_output(['git', 'rev-parse', '--short', 'HEAD'], cwd=str(path)).decode('utf-8').strip('\n')
    except:
        pass

__version__ = str(parse_version_string())

try:
    import uwsgi
    CONFIG_PATH = uwsgi.opt['config_path']
except:
    CONFIG_PATH = '/opt/wurstmineberg/config/api.json'

DOCUMENTATION_INTRO = """
<!DOCTYPE html>
<h1>Wurstmineberg API v2</h1>
<p>Welcome to the Wurstmineberg Minecraft API. Feel free to play around!</p>
<p>This is version {} of the API. Currently available API endpoints:</p>
""".format(__version__)

application = api.util.Bottle()

def config():
    try:
        with open(CONFIG_PATH) as config_file:
            loaded_config = json.load(config_file)
    except:
        loaded_config = {}
    result = {
        'isDev': loaded_config.get('isDev', False)
    }
    result['host'] = loaded_config.get('host', 'dev.wurstmineberg.de' if result['isDev'] else 'wurstmineberg.de')
    result['cache'] = pathlib.Path(loaded_config.get('cache', '/opt/wurstmineberg/dev-api-cache' if result['isDev'] else '/opt/wurstmineberg/api-cache'))
    result['jlogPath'] = pathlib.Path(loaded_config.get('jlogPath', '/opt/wurstmineberg/jlog'))
    result['logPath'] = pathlib.Path(loaded_config.get('logPath', '/opt/wurstmineberg/log'))
    result['mainWorld'] = loaded_config.get('mainWorld', 'wurstmineberg') #TODO load a systemd-minecraft world file
    result['moneysFile'] = pathlib.Path(loaded_config.get('moneysFile', '/opt/wurstmineberg/moneys/moneys.json'))
    if 'peopleConnectionString' in loaded_config:
        result['peopleConnectionString'] = loaded_config['peopleConnectionString']
    else:
        try:
            import people
        except ImportError:
            result['peopleConnectionString'] = None
        else:
            result['peopleConnectionString'] = people.DEFAULT_CONFIG['connectionstring']
    result['worldsDir'] = pathlib.Path(loaded_config.get('worldsDir', '/opt/wurstmineberg/world'))
    result['webAssets'] = pathlib.Path(loaded_config.get('webAssets', '/opt/git/github.com/wurstmineberg/assets.wurstmineberg.de/branch/dev' if result['isDev'] else '/opt/git/github.com/wurstmineberg/assets.wurstmineberg.de/master'))
    return result

CONFIG = config()

@application.route('/')
def show_index():
    """The documentation page for version 2 of the API."""
    yield DOCUMENTATION_INTRO
    yield '<table id="api-endpoints"><tbody>\n'
    yield '<tr><th style="text-align: left">Endpoint</th><th style="text-align: left">Description</th>\n'
    for route in application.routes:
        if route.rule == '/':
            yield '\n<tr><td style="white-space: nowrap; font-weight: bold;">/v2/</td><td>This documentation page for version 2 of the API.</td></tr>'
        elif '<' in route.rule:
            yield '\n<tr><td style="white-space: nowrap;">/v2' + xml.sax.saxutils.escape(route.rule) + '</td><td>' + route.callback.__doc__.format(host=CONFIG['host']) + '</td></tr>'
        else:
            yield '\n<tr><td style="white-space: nowrap;"><a href="/v2' + route.rule + '">/v2' + route.rule + '</a></td><td>' + route.callback.__doc__.format(host=CONFIG['host']) + '</td></tr>'
    yield '</tbody></table>'

@application.route('/meta/moneys.json')
def api_moneys():
    """Returns the moneys.json file."""
    with CONFIG['moneysFile'].open() as moneys_json:
        return json.load(moneys_json)

@application.route('/minecraft/items/all.json')
def api_all_items():
    """Returns the item info JSON file (<a href="http://assets.{host}/json/items.json.description.txt">documentation</a>)"""
    with (CONFIG['webAssets'] / 'json' / 'items.json').open() as items_file:
        return json.load(items_file)

@application.route('/minecraft/items/by-damage/<plugin>/<item_id>/<item_damage>.json')
def api_item_by_damage(plugin, item_id, item_damage):
    """Returns the item info for an item with the given text ID and numeric damage value."""
    ret = api_item_by_id(plugin, item_id)
    if 'damageValues' not in ret:
        bottle.abort(404, '{} has no damage variants'.format(ret.get('name', 'Item')))
    if str(item_damage) not in ret['damageValues']:
        bottle.abort(404, 'Item {} has no damage variant for damage value {}'.format(ret['stringID'], item_damage))
    ret.update(ret['damageValues'][str(item_damage)])
    del ret['damageValues']
    return ret

@application.route('/minecraft/items/by-effect/<plugin>/<item_id>/<effect_plugin>/<effect_id>.json')
def api_item_by_effect(plugin, item_id, effect_plugin, effect_id):
    """Returns the item info for an item with the given text ID, tagged with the given text effect ID."""
    ret = api_item_by_id(plugin, item_id)
    if 'effects' not in ret:
        bottle.abort(404, '{} has no effect variants'.format(ret.get('name', 'Item')))
    if effect_plugin not in ret['effects'] or effect_id not in ret['effects'][effect_plugin]:
        bottle.abort(404, 'Item {} has no effect variant for {}:{}'.format(ret['stringID'], effect_plugin, effect_id))
    ret.update(ret['effects'][effect_plugin][effect_id])
    del ret['effects']
    return ret

@application.route('/minecraft/items/by-id/<plugin>/<item_id>.json')
def api_item_by_id(plugin, item_id):
    """Returns the item info for an item with the given text ID, including variant info."""
    all_items = api_all_items()
    if plugin in all_items and item_id in all_items[plugin]:
        ret = all_items[plugin][item_id]
    else:
        bottle.abort(404, 'No item with id {}:{}'.format(plugin, item_id))
    ret['stringID'] = plugin + ':' + item_id
    return ret

@application.route('/minecraft/items/by-tag/<plugin>/<item_id>/<tag_value>.json')
def api_item_by_tag_variant(plugin, item_id, tag_value):
    """Returns the item info for an item with the given text ID, tagged with the given tag variant for the tag path specified in items.json."""
    ret = api_item_by_id(plugin, item_id)
    if 'tagPath' not in ret:
        bottle.abort(404, '{} has no tag variants'.format(ret.get('name', 'Item')))
    if str(tag_value) not in ret['tagVariants']:
        bottle.abort(404, 'Item {} has no tag variant for tag value {}'.format(ret['stringID'], tag_value))
    ret.update(ret['tagVariants'][str(tag_value)])
    del ret['tagPath']
    del ret['tagVariants']
    return ret

@application.route('/minecraft/items/render/dyed-by-id/<plugin>/<item_id>/<color>.png')
def api_item_render_dyed_png(plugin, item_id, color):
    """Returns a dyed item's base texture (color specified in hex rrggbb), rendered as a PNG image file."""
    import PIL.Image
    import PIL.ImageChops

    item = api_item_by_id(plugin, item_id)
    if isinstance(color, int):
        color_string = format(color, 'x')
    else:
        color_string = color
    color = int(color_string[:2], 16), int(color_string[2:4], 16), int(color_string[4:6], 16)
    if CONFIG['cache'].exists(): #TODO pathlib
        image_dir = os.path.join(config('cache'), 'dyed-items', plugin, item_id)
        image_name = color_string + '.png'
        image_path = os.path.join(image_dir, image_name)
        if os.path.exists(image_path): #TODO check if base texture has changed
            # dyed item has already been rendered, use the cached image
            return bottle.static_file(image_name, image_dir, mimetype='image/png')
        else:
            if not os.path.exists(os.path.join(config('cache'), 'dyed-items', plugin, item_id)):
                os.makedirs(os.path.join(config('cache'), 'dyed-items', plugin, item_id))
            image_file = open(image_path, 'wb')
    else:
        image_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        image_path = image_file.name
        image_dir, image_name = os.path.split(image_path)
    image = PIL.Image.open(os.path.join(config('webAssets'), 'img', 'grid-base', item['image']))
    image = PIL.ImageChops.multiply(image, PIL.Image.new('RGBA', image.size, color=color + (255,)))
    image.save(image_file, 'PNG')
    image_file.close()
    return bottle.static_file(image_name, image_dir, mimetype='image/png')

@application.route('/minigame/achievements/<world>/scoreboard.json')
def api_achievement_scores(world):
    """Returns an object mapping player's IDs to their current score in the achievement run."""
    raise NotImplementedError('achievement run endpoints NYI') #TODO (requires log parsing)

@application.route('/minigame/achievements/<world>/winners.json')
def api_achievement_winners(world):
    """Returns an array of IDs of all players who have completed all achievements, ordered chronologically by the time they got their last achievement. This list is emptied each time a new achievement is added to Minecraft."""
    raise NotImplementedError('achievement run endpoints NYI') #TODO (requires log parsing)

@application.route('/minigame/deathgames/log.json')
def api_death_games_log():
    """Returns the <a href="http://wiki.{host}/Death_Games">Death Games</a> log, listing attempts in chronological order."""
    with (CONFIG['logPath'] / 'deathgames.json').open() as death_games_logfile:
        return json.load(death_games_logfile)

@application.route('/people.json')
def api_player_people():
    """Returns the whole <a href="http://wiki.{host}/People_file/Version_3">people.json</a> file, except for the "gravatar" private field."""
    import people
    db = people.PeopleDB(CONFIG['peopleConnectionString']).obj_dump(version=3)
    for person in db['people'].values():
        if 'gravatar' in person:
            del person['gravatar']
    return db

@application.route('/player/<player_id>/info.json')
def api_player_info(player_id):
    """Returns the section of <a href="http://wiki.{host}/People_file/Version_3">people.json</a> that corresponds to the player."""
    import people
    db = people.PeopleDB(CONFIG['peopleConnectionString']).obj_dump(version=3)
    person = db['people'][player_id]
    if 'gravatar' in person:
        del person['gravatar']
    return person

@application.route('/world/<world>/deaths/latest.json')
def api_latest_deaths(world): #TODO multiworld
    """Returns JSON containing information about the most recent death of each player"""
    last_person = None
    people_ids = {}
    with open(config('peopleFile')) as people_json: #TODO use people module
        people_data = json.load(people_json)
        if isinstance(people_data, dict):
            people_data = people_data['people']
        for person in people_data:
            if 'id' in person and 'minecraft' in person:
                people_ids[person['minecraft']] = person['id']
    deaths = {}
    with open(os.path.join(config('logPath'), 'deaths.log')) as deaths_log: #TODO parse world log
        for line in deaths_log:
            match = re.match('([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([^@ ]+) (.*)', line)
            if match and match.group(2) in people_ids:
                last_person = person_id = people_ids[match.group(2)]
                deaths[person_id] = {
                    'cause': match.group(3),
                    'timestamp': match.group(1)
                }
    return {
        'deaths': deaths,
        'lastPerson': last_person
    }

@application.route('/world/<world>/deaths/overview.json')
def api_deaths(world): #TODO multiworld
    """Returns JSON containing information about all recorded player deaths"""
    people_ids = {}
    with open(config('peopleFile')) as people_json: #TODO use people module
        people_data = json.load(people_json)
        if isinstance(people_data, dict):
            people_data = people_data['people']
        for person in people_data:
            if 'id' in person and 'minecraft' in person:
                people_ids[person['minecraft']] = person['id']
    deaths = collections.defaultdict(list)
    with open(os.path.join(config('logPath'), 'deaths.log')) as deaths_log: #TODO parse world log
        for line in deaths_log:
            match = re.match('([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([^@ ]+) (.*)', line)
            if match and match.group(2) in people_ids:
                person_id = people_ids[match.group(2)]
                deaths[person_id].append({
                    'cause': match.group(3),
                    'timestamp': match.group(1)
                })
    return deaths

@application.route('/world/<world>/level.json')
def api_level(world): #TODO multiworld
    """Returns the level.dat encoded as JSON"""
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'level.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/maps/by-id/<identifier>.json')
def api_map_by_id(world, identifier): #TODO add multiworld support
    """Returns info about the map item with damage value &lt;identifier&gt;, see <a href="http://minecraft.gamepedia.com/Map_Item_Format">Map Item Format</a> for documentation"""
    nbt_file = os.path.join(config('serverDir'), config('worldName'), 'data', 'map_' + str(identifier) + '.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbt_file)

@application.route('/world/<world>/maps/overview.json')
def api_maps_index(world): #TODO add multiworld support
    """Returns a list of existing maps with all of their fields except for the actual colors."""
    ret = {}
    for filename in os.listdir(os.path.join(config('serverDir'), config('worldName'), 'data')): #TODO use systemd-minecraft world object
        match = re.match('map_([0-9]+).dat', filename)
        if not match:
            continue
        map_id = int(match.group(1))
        nbt_file = os.path.join(config('serverDir'), config('worldName'), 'data', filename) #TODO use systemd-minecraft world object
        nbt_dict = api.util2.nbtfile_to_dict(nbt_file)['data']
        del nbt_dict['colors']
        ret[str(map_id)] = nbt_dict
    return ret

@application.route('/world/<world>/maps/render/<identifier>.png')
def api_map_render_png(world, identifier): #TODO multiworld
    """Returns the map item with damage value &lt;identifier&gt;, rendered as a PNG image file."""
    if CONFIG['cache'].exists():
        map_dir = os.path.join(config('cache'), 'map-renders') #TODO pathlib
        map_name = str(identifier) + '.png'
        map_path = os.path.join(map_dir, map_name)
        if os.path.exists(map_path) and os.path.getmtime(map_path) > os.path.getmtime(os.path.join(config('serverDir'), config('worldName'), 'data', 'map_' + str(identifier) + '.dat')) + 60:
            # map has been rendered over a minute after it was saved, use the cached map file
            return bottle.static_file(map_name, map_dir, mimetype='image/png')
        else:
            if not os.path.exists(os.path.join(config('cache'), 'map-renders')):
                os.mkdir(os.path.join(config('cache'), 'map-renders'))
            map_file = open(map_path, 'wb')
    else:
        map_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        map_path = map_file.name
        map_dir, map_name = os.path.split(map_path)
    image = api.util.map_image(api_map_by_id(identifier))
    image.save(map_file, 'PNG')
    map_file.close()
    return bottle.static_file(map_name, map_dir, mimetype='image/png')

@application.route('/world/<world>/player/<player_id>/playerdata.json')
def api_player_data(world, player_id):
    """Returns the <a href="http://minecraft.gamepedia.com/Player.dat_format">player data</a> encoded as JSON"""
    pass #TODO get Minecraft UUID/name
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'players', player_minecraft_name + '.dat') #TODO multiworld
    if not os.path.exists(nbtfile):
        for whitelist_entry in json.loads(api_whitelist()): #TODO add support for non whitelisted players
            if whitelist_entry['name'] == player_minecraft_name:
                uuid = whitelist_entry['uuid']
                break
        else:
            uuid = api_player_info(player_minecraft_name)['minecraftUUID']
        if '-' not in uuid:
            uuid = uuid[:8] + '-' + uuid[8:12] + '-' + uuid[12:16] + '-' + uuid[16:20] + '-' + uuid[20:]
        nbtfile = os.path.join(config('serverDir'), config('worldName'), 'playerdata', uuid + '.dat') #TODO multiworld
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/player/<player_id>/stats.json')
def api_player_stats(world, player_id):
    """Returns the player's stats formatted as JSON with stats grouped into objects by category"""

    def api_stats(player_minecraft_name): #TODO deprecate in favor of api_player_stats
        """Returns the stats JSON file from the server, also accepts the player id instead of the Minecraft name"""
        try:
            player_minecraft_name = api_player_info(player_minecraft_name)['minecraft']
        except:
            pass # no such person or already correct
        stats_file = os.path.join(config('serverDir'), config('worldName'), 'stats', player_minecraft_name + '.json') #TODO use systemd-minecraft world object
        if not os.path.exists(stats_file):
            for whitelist_entry in json.loads(api_whitelist()):
                if whitelist_entry['name'] == player_minecraft_name:
                    uuid = whitelist_entry['uuid']
                    break
            else:
                uuid = api_player_info(player_minecraft_name)['minecraftUUID']
            if '-' not in uuid:
                uuid = uuid[:8] + '-' + uuid[8:12] + '-' + uuid[12:16] + '-' + uuid[16:20] + '-' + uuid[20:]
            stats_file = os.path.join(config('serverDir'), config('worldName'), 'stats', uuid + '.json') #TODO use systemd-minecraft world object
        with open(stats_file) as stats:
            return json.load(stats)

    stats = api_stats(player_id) #TODO deprecate that endpoint; multiworld
    ret = {}
    for stat_name, value in stats.items():
        parent = ret
        key_path = stat_name.split('.')
        for key in key_path[:-1]:
            if key not in parent:
                parent[key] = {}
            parent = parent[key]
        parent[key_path[-1]] = value #TODO add support for summary stats (stat.drop)
    return ret

@application.route('/world/<world>/playerdata/all.json')
def api_player_data_all(world): #TODO multiworld
    """Returns the player data of all known players, encoded as JSON"""
    nbtdicts = {}
    for user in playernames():
        with contextlib.suppress(FileNotFoundError):
            nbtdata = api_player_data(user)
        nbtdicts[user] = nbtdata
    return nbtdicts

@application.route('/world/<world>/playerdata/by-id/<identifier>.json')
def api_player_data_by_id(world, identifier): #TODO multiworld, player IDs
    """Returns a dictionary with player IDs as the keys, and their player data fields &lt;identifier&gt; as the values"""
    all_data = api_player_data_all()
    data = {}
    for player in all_data:
        playerdata = all_data[player]
        for name in playerdata:
            if name == identifier:
                data[player] = playerdata[name]
    return data

@application.route('/world/<world>/playerstats/all.json')
def api_playerstats(world): #TODO multiworld
    """Returns all player stats in one file. This file can be potentially big. Please use one of the other endpoints if possible."""
    data = {}
    people = None
    directory = os.path.join(config('serverDir'), config('worldName'), 'stats') #TODO use systemd-minecraft world object
    for root, dirs, files in os.walk(directory):
        for file_name in files:
            if file_name.endswith(".json"):
                with open(os.path.join(directory, file_name), 'r') as playerfile:
                    name = os.path.splitext(file_name)[0]
                    uuid_filename = re.match('([0-9a-f]{8})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]{4})-([0-9a-f]+)$', name)
                    if uuid_filename:
                        uuid = ''.join(uuid_filename.groups())
                        if people is None:
                            with open(config('peopleFile')) as people_json: #TODO use people module
                                people = json.load(people_json)
                                if isinstance(data, dict):
                                    people = people['people']
                        for person in people:
                            if (person.get('minecraftUUID') == uuid or person.get('minecraftUUID') == name) and 'minecraft' in person:
                                name = person['minecraft']
                                break
                    data[name] = json.loads(playerfile.read())
    return data

@application.route('/world/<world>/playerstats/achievement.json')
def api_playerstats_achievements(world): #TODO multiworld
    """Returns all achievement stats in one file"""
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

@application.route('/world/<world>/playerstats/by-id/<identifier>.json')
def api_playerstats_by_id(world, identifier): #TODO multiworld
    """Returns the stat item &lt;identifier&gt; from all player stats"""
    alldata = api_playerstats()
    data = {}
    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        if identifier in playerdata:
            data[player] = playerdata[identifier]
    if len(data) == 0:
        bottle.abort(404, 'Identifier not found')
    return data

@application.route('/world/<world>/playerstats/entity.json')
def api_playerstats_entities(world): #TODO multiworld
    """Returns all entity stats in one file"""
    alldata = api_playerstats()
    data = {}
    entityActions = ['killEntity', 'entityKilledBy']
    for player in alldata:
        playerdata = alldata[player]
        playerdict = {}
        for statstr in playerdata:
            value = playerdata[statstr]
            stat = statstr.split('.')
            if stat[0] == 'stat' and stat[1] in entityActions:
                playerdict[statstr] = value
        data[player] = playerdict
    return data

@application.route('/world/<world>/playerstats/general.json')
def api_playerstats_general(world): #TODO multiworld
    """Returns all general stats in one file"""
    all_data = api_playerstats()
    data = {}
    for player, player_data in all_data.items():
        player_dict = {}
        for stat_str, value in player_data.items():
            stat = stat_str.split('.')
            if stat[0] == 'stat' and len(stat) == 2:
                player_dict[stat_str] = value
            elif stat[0] == 'stat' and stat[1] == 'pickup':
                if 'stat.pickup' not in player_dict:
                    player_dict['stat.pickup'] = 0
                player_dict['stat.pickup'] += value
        data[player] = player_dict
    return data

@application.route('/world/<world>/playerstats/item.json')
def api_playerstats_items(world): #TODO multiworld
    """Returns all item and block stats in one file"""
    all_data = api_playerstats()
    data = {}
    item_actions = 'useItem', 'craftItem', 'breakItem', 'mineBlock', 'pickup', 'drop'
    for player, player_data in all_data.items():
        player_dict = {}
        for stat_str, value in player_data.items():
            stat = stat_str.split('.')
            if stat[0] == 'stat' and stat[1] in item_actions:
                player_dict[stat_str] = value
        data[player] = player_dict
    return data

@application.route('/world/<world>/scoreboard.json')
def api_scoreboard(world): #TODO multiworld
    """Returns the scoreboard data encoded as JSON"""
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'data', 'scoreboard.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/sessions/lastseen.json')
def api_sessions_last_seen_world(world): #TODO multiworld
    """Returns the last known session for each player"""
    matches = {
        'join': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) joined ([A-Za-z0-9_]{1,16})',
        'leave': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) left ([A-Za-z0-9_]{1,16})',
        'restart': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @restart',
        'start': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @start ([^ ]+)',
        'stop': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @stop'
    }
    ret = {}
    with open(os.path.join(config('logPath'), 'logins.log')) as logins_log: #TODO parse world logs
        for log_line in logins_log:
            for match_type, match_string in matches.items():
                match = re.match(match_string, log_line.strip('\n'))
                if match:
                    break
            else:
                continue
            if match_type == 'restart':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'restart'
            elif match_type == 'start':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'serverStartOverride'
            elif match_type == 'stop':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'serverStop'
            elif match_type == 'join':
                if match.group(2) == '?':
                    continue
                ret[match.group(2)] = {
                    'joinTime': match.group(1),
                    'minecraftNick': match.group(3),
                    'person': match.group(2)
                }
            elif match_type == 'leave':
                if match.group(2) not in ret:
                    continue
                ret[match.group(2)]['leaveTime'] = match.group(1)
                ret[match.group(2)]['leaveReason'] = 'logout'
    for session in ret.values():
        if 'leaveTime' not in session:
            session['leaveReason'] = 'currentlyOnline'
    return ret

@application.route('/world/<world>/sessions/overview.json')
def api_sessions(world): #TODO multiworld
    """Returns known players' sessions since the first recorded server restart"""
    #TODO log parsing
    uptimes = []
    current_uptime = None
    matches = {
        'join': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) joined ([A-Za-z0-9_]{1,16})',
        'leave': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) left ([A-Za-z0-9_]{1,16})',
        'restart': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @restart',
        'start': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @start ([^ ]+)',
        'stop': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @stop'
    }
    with open(os.path.join(config('logPath'), 'logins.log')) as logins_log: #TODO parse world logs
        for log_line in logins_log:
            for match_type, match_string in matches.items():
                match = re.match(match_string, log_line.strip('\n'))
                if match:
                    break
            else:
                continue
            if match_type == 'restart':
                if current_uptime is not None:
                    current_uptime['endTime'] = match.group(1)
                    for session in current_uptime.get('sessions', []):
                        if 'leaveTime' not in session:
                            session['leaveTime'] = match.group(1)
                            session['leaveReason'] = 'restart'
                    uptimes.append(current_uptime)
                current_uptime = {'startTime': match.group(1)}
            elif match_type == 'start':
                if current_uptime is not None:
                    current_uptime['endTime'] = match.group(1)
                    for session in current_uptime.get('sessions', []):
                        if 'leaveTime' not in session:
                            session['leaveTime'] = match.group(1)
                            session['leaveReason'] = 'serverStartOverride'
                    uptimes.append(current_uptime)
                current_uptime = {
                    'startTime': match.group(1),
                    'version': match.group(2)
                }
            elif match_type == 'stop':
                if current_uptime is not None:
                    current_uptime['endTime'] = match.group(1)
                    for session in current_uptime.get('sessions', []):
                        if 'leaveTime' not in session:
                            session['leaveTime'] = match.group(1)
                            session['leaveReason'] = 'serverStop'
                    uptimes.append(current_uptime)
            elif current_uptime is None or match.group(2) == '?':
                continue
            elif match_type == 'join':
                if 'sessions' not in current_uptime:
                    current_uptime['sessions'] = []
                current_uptime['sessions'].append({
                    'joinTime': match.group(1),
                    'minecraftNick': match.group(3),
                    'person': match.group(2)
                })
            elif match_type == 'leave':
                for session in current_uptime.get('sessions', []):
                    if 'leaveTime' not in session and session['person'] == match.group(2):
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'logout'
                        break
    if current_uptime is not None:
        for session in current_uptime.get('sessions', []):
            if 'leaveTime' not in session:
                session['leaveReason'] = 'currentlyOnline'
        uptimes.append(current_uptime)
    return {'uptimes': uptimes}

@application.route('/world/<world>/status.json')
def api_short_world_status(world): #TODO multiworld
    """Returns JSON containing whether the server is online, the current Minecraft version, and the list of people who are online. Requires systemd-minecraft and mcstatus."""
    import mcstatus

    server = mcstatus.MinecraftServer.lookup('wurstmineberg.de')
    try:
        status = server.status()
    except ConnectionRefusedError:
        main_world = minecraft.World()
        return {
            'list': [],
            'on': false,
            'version': main_world.version()
        }
    else:
        with open(config('peopleFile')) as people_json: #TODO use people module
            people_data = json.load(people_json)
        if isinstance(people_data, dict):
            people_data = people_data['people']

        def wmb_id(player_info):
            for person_data in people_data:
                if 'minecraftUUID' in person_data and uuid.UUID(person_data['minecraftUUID']) == uuid.UUID(player_info.id):
                    return person_data['id']
            for person_data in people_data:
                if person_data['minecraft'] == player_info.name:
                    return person_data['id']

        return {
            'list': [wmb_id(player) for player in (status.players.sample or [])],
            'on': True,
            'version': status.version.name
        }

@application.route('/world/<world>/villages/end.json')
def api_villages_end(): #TODO multiworld
    """Returns the villages.dat in the End, encoded as JSON"""
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'data/villages_end.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/villages/nether.json')
def api_villages_nether(): #TODO multiworld
    """Returns the villages.dat in the Nether, encoded as JSON"""
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'data/villages_nether.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/villages/overworld.json')
def api_villages_overworld(): #TODO multiworld
    """Returns the villages.dat in the Overworld, encoded as JSON"""
    nbtfile = os.path.join(config('serverDir'), config('worldName'), 'data/villages.dat') #TODO use systemd-minecraft world object
    return api.util2.nbtfile_to_dict(nbtfile)

@application.route('/world/<world>/whitelist.json')
def api_whitelist(world): #TODO multiworld
    """For UUID-based worlds (Minecraft 1.7.6 and later), returns the whitelist. For older worlds, the behavior is undefined."""
    with open(os.path.join(config('serverDir'), 'whitelist.json')) as whitelist: #TODO use systemd-minecraft world object
        return whitelist.read()

@application.route('/server/players.json')
def api_playernames():
    """Returns an array of all known player IDs (Wurstmineberg IDs and Minecraft UUIDs)"""
    return json.dumps(api.util2.all_players(), sort_keys=True, indent=4)

@application.route('/server/sessions/lastseen.json')
def api_sessions_last_seen_all(): #TODO multiworld
    """Returns the last known session for each player"""
    matches = {
        'join': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) joined ([A-Za-z0-9_]{1,16})',
        'leave': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([a-z0-9]+|\\?) left ([A-Za-z0-9_]{1,16})',
        'restart': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @restart',
        'start': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @start ([^ ]+)',
        'stop': '([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) @stop'
    }
    ret = {}
    with open(os.path.join(config('logPath'), 'logins.log')) as logins_log: #TODO parse server logs
        for log_line in logins_log:
            for match_type, match_string in matches.items():
                match = re.match(match_string, log_line.strip('\n'))
                if match:
                    break
            else:
                continue
            if match_type == 'restart':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'restart'
            elif match_type == 'start':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'serverStartOverride'
            elif match_type == 'stop':
                for session in ret.values():
                    if 'leaveTime' not in session:
                        session['leaveTime'] = match.group(1)
                        session['leaveReason'] = 'serverStop'
            elif match_type == 'join':
                if match.group(2) == '?':
                    continue
                ret[match.group(2)] = {
                    'joinTime': match.group(1),
                    'minecraftNick': match.group(3),
                    'person': match.group(2)
                }
            elif match_type == 'leave':
                if match.group(2) not in ret:
                    continue
                ret[match.group(2)]['leaveTime'] = match.group(1)
                ret[match.group(2)]['leaveReason'] = 'logout'
    for session in ret.values():
        if 'leaveTime' not in session:
            session['leaveReason'] = 'currentlyOnline'
    return ret

@application.route('/server/worlds.json')
def api_worlds():
    """Returns an object mapping existing world names to short status summaries"""
    raise NotImplementedError('worlds endpoint NYI') #TODO