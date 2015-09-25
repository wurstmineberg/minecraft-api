import sys

sys.path.append('/opt/py')

import bottle
import collections
import contextlib
import hashlib
import io
import json
import minecraft
import nbt.nbt
import os
import os.path
import pathlib
import re
import subprocess
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

DOCUMENTATION_INTRO = """
<!DOCTYPE html>
<h1>Wurstmineberg API v2</h1>
<p>Welcome to the Wurstmineberg Minecraft API. Feel free to play around!</p>
<p>This is version {} of the API. Currently available API endpoints:</p>
""".format(__version__)

application = api.util.Bottle()

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
            yield '\n<tr><td style="white-space: nowrap;">/v2' + xml.sax.saxutils.escape(route.rule) + '</td><td>' + route.callback.__doc__.format(host=api.util.CONFIG['host']) + '</td></tr>'
        else:
            yield '\n<tr><td style="white-space: nowrap;"><a href="/v2' + route.rule + '">/v2' + route.rule + '</a></td><td>' + route.callback.__doc__.format(host=api.util.CONFIG['host']) + '</td></tr>'
    yield '</tbody></table>'

@api.util2.json_route(application, '/meta/config/api')
def api_api_config():
    """Returns the API configuration, for debugging purposes."""
    result = {key: (str(value) if isinstance(value, pathlib.Path) else value) for key, value in api.util.CONFIG.items()}
    result['configPath'] = str(api.util.CONFIG_PATH)
    return result

@api.util2.json_route(application, '/meta/moneys')
def api_moneys():
    """Returns the moneys.json file."""
    with api.util.CONFIG['moneysFile'].open() as moneys_json:
        return json.load(moneys_json)

@api.util2.json_route(application, '/minecraft/items/all')
def api_all_items():
    """Returns the item info JSON file (<a href="http://assets.{host}/json/items.json.description.txt">documentation</a>)"""
    with (api.util.CONFIG['webAssets'] / 'json' / 'items.json').open() as items_file:
        return json.load(items_file)

@api.util2.json_route(application, '/minecraft/items/by-damage/<plugin>/<item_id>/<item_damage>')
@api.util2.decode_args
def api_item_by_damage(plugin, item_id, item_damage: int):
    """Returns the item info for an item with the given text ID and numeric damage value."""
    ret = api_item_by_id(plugin, item_id)
    if 'damageValues' not in ret:
        bottle.abort(404, '{} has no damage variants'.format(ret.get('name', 'Item')))
    if str(item_damage) not in ret['damageValues']:
        bottle.abort(404, 'Item {}:{} has no damage variant for damage value {}'.format(plugin, item_id, item_damage))
    ret.update(ret['damageValues'][str(item_damage)])
    del ret['damageValues']
    return ret

@api.util2.json_route(application, '/minecraft/items/by-effect/<plugin>/<item_id>/<effect_plugin>/<effect_id>')
def api_item_by_effect(plugin, item_id, effect_plugin, effect_id):
    """Returns the item info for an item with the given text ID, tagged with the given text effect ID."""
    ret = api_item_by_id(plugin, item_id)
    if 'effects' not in ret:
        bottle.abort(404, '{} has no effect variants'.format(ret.get('name', 'Item')))
    if effect_plugin not in ret['effects'] or effect_id not in ret['effects'][effect_plugin]:
        bottle.abort(404, 'Item {}:{} has no effect variant for {}:{}'.format(plugin, item_id, effect_plugin, effect_id))
    ret.update(ret['effects'][effect_plugin][effect_id])
    del ret['effects']
    return ret

@api.util2.json_route(application, '/minecraft/items/by-id/<plugin>/<item_id>')
def api_item_by_id(plugin, item_id):
    """Returns the item info for an item with the given text ID, including variant info."""
    all_items = api_all_items()
    if plugin in all_items and item_id in all_items[plugin]:
        ret = all_items[plugin][item_id]
    else:
        bottle.abort(404, 'No item with id {}:{}'.format(plugin, item_id))
    return ret

@api.util2.json_route(application, '/minecraft/items/by-tag/<plugin>/<item_id>/<tag_value>')
def api_item_by_tag_variant(plugin, item_id, tag_value):
    """Returns the item info for an item with the given text ID, tagged with the given tag variant for the tag path specified in items.json."""
    ret = api_item_by_id(plugin, item_id)
    if 'tagPath' not in ret:
        bottle.abort(404, '{} has no tag variants'.format(ret.get('name', 'Item')))
    if str(tag_value) not in ret['tagVariants']:
        bottle.abort(404, 'Item {}:{} has no tag variant for tag value {}'.format(plugin, item_id, tag_value))
    ret.update(ret['tagVariants'][str(tag_value)])
    del ret['tagPath']
    del ret['tagVariants']
    return ret

@application.route('/minecraft/items/render/dyed-by-id/<plugin>/<item_id>/<color>.png')
@api.util2.decode_args
def api_item_render_dyed_png(plugin, item_id, color: 'color'):
    """Returns a dyed item's base texture (color specified in hex rrggbb), rendered as a PNG image file."""
    cache_path = 'dyed-items/{}/{}/{:02x}{:02x}{:02x}.png'.format(plugin, item_id, *color)

    def image_func():
        import PIL.Image
        import PIL.ImageChops

        item = api_item_by_id(plugin, item_id)

        image = PIL.Image.open(api.util.CONFIG['webAssets'] / 'img' / 'grid-base' / item['image']) #TODO remove str cast, requires a feature from the next Pillow release after 2.9.0
        image = PIL.ImageChops.multiply(image, PIL.Image.new('RGBA', image.size, color=color + (255,)))
        return image

    def cache_check(image_path):
        if not image_path.exists():
            return False
        return True #TODO check if base texture has changed

    return api.util2.cached_image(cache_path, image_func, cache_check)

@api.util2.json_route(application, '/minigame/achievements/<world>/scoreboard')
@api.util2.decode_args
def api_achievement_scores(world: minecraft.World):
    """Returns an object mapping player's IDs to their current score in the achievement run."""
    raise NotImplementedError('achievement run endpoints NYI') #TODO (requires log parsing)

@api.util2.json_route(application, '/minigame/achievements/<world>/winners')
@api.util2.decode_args
def api_achievement_winners(world: minecraft.World):
    """Returns an array of IDs of all players who have completed all achievements, ordered chronologically by the time they got their last achievement. This list is emptied each time a new achievement is added to Minecraft."""
    raise NotImplementedError('achievement run endpoints NYI') #TODO (requires log parsing)

@api.util2.json_route(application, '/minigame/deathgames/log')
def api_death_games_log():
    """Returns the <a href="http://wiki.{host}/Death_Games">Death Games</a> log, listing attempts in chronological order."""
    with (api.util.CONFIG['logPath'] / 'deathgames.json').open() as death_games_logfile:
        return json.load(death_games_logfile)

@api.util2.json_route(application, '/people')
def api_player_people():
    """Returns the whole <a href="http://wiki.{host}/People_file/Version_3">people.json</a> file, except for the "gravatar" private field, which is replaced by the gravatar URL."""
    import people

    db = people.get_people_db().obj_dump(version=3)
    for person in db['people'].values():
        if 'gravatar' in person:
            person['gravatar'] = 'http://www.gravatar.com/avatar/{}'.format(hashlib.md5(person['gravatar'].encode('utf-8')).hexdigest())
    return db

@api.util2.json_route(application, '/player/<player>/info')
@api.util2.decode_args
def api_player_info(player: api.util2.Player):
    """Returns the section of <a href="http://wiki.{host}/People_file/Version_3">people.json</a> that corresponds to the player, except for the "gravatar" private field, which is replaced by the gravatar URL."""
    person_data = player.data
    if 'gravatar' in person_data:
        person_data['gravatar'] = 'http://www.gravatar.com/avatar/{}'.format(hashlib.md5(person_data['gravatar'].encode('utf-8')).hexdigest())
    return person_data

@application.route('/player/<player>/skin/render/front/<size>.png')
@api.util2.decode_args
def api_skin_render_front_png(player: api.util2.Player, size: range(1025)):
    """Returns a player skin in front view (including the overlay layers), as a &lt;size&gt;×(2*&lt;size&gt;)px PNG image file. Requires playerhead."""
    def image_func():
        import playerhead

        return playerhead.body(player.data['minecraft']['nicks'][-1], profile_id=player.uuid).resize((size, 2 * size))

    return api.util2.cached_image('skins/front-views/{}/{}.png'.format(size, player), image_func, api.util2.skin_cache_check)

@application.route('/player/<player>/skin/render/head/<size>.png')
@api.util2.decode_args
def api_skin_render_head_png(player: api.util2.Player, size: range(1025)):
    """Returns a player skin's head (including the hat layer), as a &lt;size&gt;×&lt;size&gt;px PNG image file. Requires playerhead."""
    def image_func():
        import playerhead

        return playerhead.head(player.data['minecraft']['nicks'][-1], profile_id=player.uuid).resize((size, size))

    return api.util2.cached_image('skins/heads/{}/{}.png'.format(size, player), image_func, api.util2.skin_cache_check)

@api.util2.json_route(application, '/world/<world>/chunks/overworld/column/<x>/<z>')
@api.util2.decode_args
def api_chunk_column_overworld(world: minecraft.World, x: int, z: int):
    """Returns the given chunk column in JSON-encoded <a href="http://minecraft.gamepedia.com/Anvil_file_format">Anvil</a> NBT."""
    import anvil

    region = anvil.Region(world.world_path / 'region' / 'r.{}.{}.mca'.format(x // 32, z // 32))
    chunk_column = region.chunk_column(x, z)
    return api.util2.nbt_to_dict(chunk_column.data)

@api.util2.json_route(application, '/world/<world>/chunks/overworld/chunk/<x>/<y>/<z>')
@api.util2.decode_args
def api_chunk_info_overworld(world: minecraft.World, x: int, y: range(16), z: int):
    """Returns information about the given chunk section in JSON format. The nested arrays can be indexed in y-z-x order."""

    def nybble(data, idx):
        result = data[idx // 2]
        if idx % 2:
            return result & 15
        else:
            return result >> 4

    column = api_chunk_column_overworld(world, x, z)
    for section in column['Level']['Sections']:
        if section['Y'] == y:
            break
    else:
        section = None
    with (api.util.CONFIG['webAssets'] / 'json' / 'biomes.json').open() as biomes_file:
        biomes = json.load(biomes_file)
    with (api.util.CONFIG['webAssets'] / 'json' / 'items.json').open() as items_file:
        items = json.load(items_file)
    layers = []
    for layer in range(16):
        block_y = y * 16 + layer
        rows = []
        for row in range(16):
            block_z = z * 16 + row
            blocks = []
            for block in range(16):
                block_x = x * 16 + block
                block_info ={
                    'x': block_x,
                    'y': block_y,
                    'z': block_z
                }
                if 'Biomes' in column['Level']:
                    block_info['biome'] = biomes['biomes'][str(column['Level']['Biomes'][16 * row + block])]['id']
                if section is not None:
                    block_index = 256 * layer + 16 * row + block
                    block_id = section['Blocks'][block_index]
                    if 'Add' in section:
                        block_id += nybble(section['Add'], block_index) << 8
                    block_info['id'] = block_id
                    for plugin, plugin_items in items.items():
                        for item_id, item_info in plugin_items.items():
                            if 'blockID' in item_info and item_info['blockID'] == block_id:
                                block_info['id'] = '{}:{}'.format(plugin, item_id)
                                break
                    block_info['damage'] = nybble(section['Data'], block_index)
                    block_info['blockLight'] = nybble(section['BlockLight'], block_index)
                    block_info['skyLight'] = nybble(section['SkyLight'], block_index)
                blocks.append(block_info)
            rows.append(blocks)
        layers.append(rows)
    if 'Entities' in column['Level']:
        for entity in column['Level']['Entities']:
            if y * 16 <= entity['Pos'][1] < y * 16 + 16: # make sure the entity is in the right section
                block_info = layers[int(entity['Pos'][1]) & 15][int(entity['Pos'][2]) & 15][int(entity['Pos'][0]) & 15]
                if 'entities' not in block_info:
                    block_info['entities'] = []
                block_info['entities'].append(entity)
    if 'TileEntities' in column['Level']:
        for tile_entity in column['Level']['TileEntities']:
            if y * 16 <= tile_entity['y'] < y * 16 + 16: # make sure the entity is in the right section
                block_info = layers[tile_entity['y'] & 15][tile_entity['z'] & 15][tile_entity['x'] & 15]
                del tile_entity['x']
                del tile_entity['y']
                del tile_entity['z']
                if 'tileEntities' in block_info:
                    block_info['tileEntities'].append(tile_entity)
                elif 'tileEntity' in block_info:
                    block_info['tileEntities'] = [block_info['tileEntity'], tile_entity]
                    del block_info['tileEntity']
                else:
                    block_info['tileEntity'] = tile_entity
    return layers

@api.util2.json_route(application, '/world/<world>/deaths/latest')
@api.util2.decode_args
def api_latest_deaths(world: minecraft.World): #TODO multiworld
    """Returns JSON containing information about the most recent death of each player"""
    import people

    last_person = None
    people_ids = {}
    people_data = people.get_people_db().obj_dump(version=3)['people']
    for wmb_id, person in people_data.items():
        if 'minecraft' in person: #TODO fix for v3 format
            people_ids[person['minecraft']] = wmb_id
    deaths = {}
    with (api.util.CONFIG['logPath'] / 'deaths.log').open() as deaths_log: #TODO parse world log
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

@api.util2.json_route(application, '/world/<world>/deaths/overview')
@api.util2.decode_args
def api_deaths(world: minecraft.World): #TODO multiworld
    """Returns JSON containing information about all recorded player deaths"""
    people_ids = {}
    people_data = people.get_people_db().obj_dump(version=3)['people']
    for wmb_id, person in people_data.items():
        if 'minecraft' in person: #TODO fix for v3 format
            people_ids[person['minecraft']] = wmb_id
    deaths = collections.defaultdict(list)
    with (api.util.CONFIG['logPath'] / 'deaths.log').open() as deaths_log: #TODO parse world log
        for line in deaths_log:
            match = re.match('([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) ([^@ ]+) (.*)', line)
            if match and match.group(2) in people_ids:
                person_id = people_ids[match.group(2)]
                deaths[person_id].append({
                    'cause': match.group(3),
                    'timestamp': match.group(1)
                })
    return deaths

@api.util2.json_route(application, '/world/<world>/level')
@api.util2.decode_args
def api_level(world: minecraft.World):
    """Returns the level.dat encoded as JSON"""
    nbt_file = world.world_path / 'level.dat'
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/maps/by-id/<identifier>')
@api.util2.decode_args
def api_map_by_id(world: minecraft.World, identifier: int):
    """Returns info about the map item with damage value &lt;identifier&gt;, see <a href="http://minecraft.gamepedia.com/Map_Item_Format">Map Item Format</a> for documentation"""
    nbt_file = world.world_path / 'data' / 'map_{}.dat'.format(identifier)
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/maps/overview')
@api.util2.decode_args
def api_maps_index(world: minecraft.World):
    """Returns a list of existing maps with all of their fields except for the actual colors."""
    ret = {}
    for map_file in (world.world_path / 'data').iterdir():
        match = re.match('map_([0-9]+).dat', map_file.name)
        if not match:
            continue
        map_id = int(match.group(1))
        nbt_dict = api.util2.nbtfile_to_dict(map_file)['data']
        del nbt_dict['colors']
        ret[str(map_id)] = nbt_dict
    return ret

@application.route('/world/<world>/maps/render/<identifier>.png')
@api.util2.decode_args
def api_map_render_png(world: minecraft.World, identifier: int):
    """Returns the map item with damage value &lt;identifier&gt;, rendered as a PNG image file."""
    def cache_check(image_path):
        if not image_path.exists():
            return False
        if image_path.stat().st_mtime < (world.world_path / 'data' / 'map_{}.dat'.format(identifier)).stat().st_mtime + 60:
            return False
        return True

    def image_func():
        return api.util.map_image(api_map_by_id(world, identifier))

    return api.util2.cached_image('map-renders/{}.png'.format(identifier), image_func, cache_check)

@api.util2.json_route(application, '/world/<world>/player/<player>/playerdata')
@api.util2.decode_args
def api_player_data(world: minecraft.World, player: api.util2.Player):
    """Returns the <a href="http://minecraft.gamepedia.com/Player.dat_format">player data</a> encoded as JSON"""
    nbt_file = world.world_path / 'playerdata' / '{}.dat'.format(player.uuid)
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/player/<player>/stats')
@api.util2.decode_args
def api_player_stats(world: minecraft.World, player: api.util2.Player):
    """Returns the player's stats formatted as JSON with stats grouped into objects by category"""
    stats_path = world.world_path / 'stats' / '{}.json'.format(player.uuid)
    if not stats_path.exists():
        player_minecraft_name = player.data['minecraft']['nicks'][-1]
        stats_path = world.world_path / 'stats' / '{}.json'.format(player_minecraft_name)
    with stats_path.open() as stats_file:
        stats = json.load(stats_file)
    return api.util.format_stats(stats)

@api.util2.json_route(application, '/world/<world>/playerdata/all')
@api.util2.decode_args
def api_player_data_all(world: minecraft.World):
    """Returns the player data of all known players, encoded as JSON"""
    nbt_dicts = {}
    for data_path in (world.world_path / 'playerdata').iterdir():
        if data_path.suffix == '.dat':
            player = api.util2.Player(data_path.stem)
            nbt_dicts[str(player)] = api.util2.nbtfile_to_dict(data_path)
    return nbt_dicts

@api.util2.json_route(application, '/world/<world>/playerdata/by-id/<identifier>')
@api.util2.decode_args
def api_player_data_by_id(world: minecraft.World, identifier):
    """Returns a dictionary with player IDs as the keys, and their player data fields &lt;identifier&gt; as the values"""
    all_data = api_player_data_all(world)
    data = {}
    for player in all_data:
        playerdata = all_data[player]
        for name in playerdata:
            if name == identifier:
                data[player] = playerdata[name]
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/all')
@api.util2.decode_args
def api_playerstats(world: minecraft.World):
    """Returns all stats for all players in one file."""
    data = {}
    people = None
    stats_dir = world.world_path / 'stats'
    for stats_path in stats_dir.iterdir():
        if stats_path.suffix == '.json':
            with stats_path.open() as stats_file:
                person = api.util2.Player(stats_path.stem)
                data[str(person)] = api.util.format_stats(json.load(stats_file))
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/achievement')
@api.util2.decode_args
def api_playerstats_achievements(world: minecraft.World):
    """Returns all achievement stats in one file"""
    all_data = api_playerstats(world)
    data = {}
    for player_id, player_data in all_data.items():
        if 'achievement' in player_data:
            data[player_id] = player_data['achievement']
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/by-id/<identifier>')
@api.util2.decode_args
def api_playerstats_by_id(world: minecraft.World, identifier):
    """Returns the stat item &lt;identifier&gt; from all player stats."""
    all_data = api_playerstats(world)
    key_path = identifier.split('.')
    data = {}
    for player_id, player_data in all_data.items():
        parent = player_data
        for key in key_path[:-1]:
            if key not in parent:
                parent[key] = {}
            elif not isinstance(parent[key], dict):
                parent[key] = {'summary': parent[key]}
            parent = parent[key]
        if key_path[-1] in parent:
            data[player_id] = parent[key_path[-1]]
    if len(data) == 0: #TODO only error if the stat is also not found in assets
        bottle.abort(404, 'Identifier not found')
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/entity')
@api.util2.decode_args
def api_playerstats_entities(world: minecraft.World):
    """Returns all entity stats in one file"""
    all_data = api_playerstats(world)
    data = {}
    for player_id, player_data in all_data.items():
        for stat_str, value in player_data.get('stat', {}).items():
            if stat_str in ('killEntity', 'entityKilledBy'):
                if player_id not in data:
                    data[player_id] = {}
                data[player_id][stat_str] = value
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/general')
@api.util2.decode_args
def api_playerstats_general(world: minecraft.World):
    """Returns all general stats in one file"""
    all_data = api_playerstats(world)
    non_general = (
        'breakItem',
        'craftItem',
        'drop',
        'entityKilledBy',
        'killEntity',
        'mineBlock',
        'pickup',
        'useItem'
    )
    data = {}
    for player_id, player_data in all_data.items():
        filtered = {stat_id: stat for stat_id, stat in player_data.get('stat', {}).items() if stat_id not in non_general}
        if len(filtered) > 0:
            data[player_id] = filtered
    return data

@api.util2.json_route(application, '/world/<world>/playerstats/item')
@api.util2.decode_args
def api_playerstats_items(world: minecraft.World):
    """Returns all item and block stats in one file"""
    all_data = api_playerstats(world)
    data = {}
    for player_id, player_data in all_data.items():
        for stat_str, value in player_data.get('stat', {}).items():
            if stat_str in ('useItem', 'craftItem', 'breakItem', 'mineBlock', 'pickup', 'drop'):
                if player_id not in data:
                    data[player_id] = {}
                data[player_id][stat_str] = value
    return data

@api.util2.json_route(application, '/world/<world>/scoreboard')
@api.util2.decode_args
def api_scoreboard(world: minecraft.World):
    """Returns the scoreboard data encoded as JSON"""
    nbt)file = world.world_path / 'data' / 'scoreboard.dat'
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/sessions/lastseen')
@api.util2.decode_args
def api_sessions_last_seen_world(world: minecraft.World): #TODO multiworld
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

@api.util2.json_route(application, '/world/<world>/sessions/overview')
@api.util2.decode_args
def api_sessions(world: minecraft.World): #TODO multiworld
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

@api.util2.json_route(application, '/world/<world>/status')
@api.util2.decode_args
def api_world_status(world: minecraft.World):
    """Returns JSON containing info about the given world, including whether the server is running, the current Minecraft version, and the list of people who are online. Requires mcstatus."""
    import mcstatus

    result = api.util2.short_world_status(world)
    server = mcstatus.MinecraftServer.lookup(api.util.CONFIG['worldHost'] if world.is_main else '{}.{}'.format(world, api.util.CONFIG['worldHost']))
    try:
        status = server.status()
    except ConnectionRefusedError:
        result['list'] = []
    else:
        result['list'] = [str(api.util2.Player(player.id)) for player in (status.players.sample or [])]
    return result

@api.util2.json_route(application, '/world/<world>/villages/end')
@api.util2.decode_args
def api_villages_end(world: minecraft.World):
    """Returns the villages.dat in the End, encoded as JSON"""
    nbt_file = world.world_path / 'data' / 'villages_end.dat'
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/villages/nether')
@api.util2.decode_args
def api_villages_nether(world: minecraft.World):
    """Returns the villages.dat in the Nether, encoded as JSON"""
    nbt_file = world.world_path / 'data' / 'villages_nether.dat'
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/villages/overworld')
@api.util2.decode_args
def api_villages_overworld(world: minecraft.World):
    """Returns the villages.dat in the Overworld, encoded as JSON"""
    nbt_file = world.world_path / 'data' / 'villages.dat'
    return api.util2.nbtfile_to_dict(nbt_file)

@api.util2.json_route(application, '/world/<world>/whitelist')
@api.util2.decode_args
def api_whitelist(world: minecraft.World):
    """Returns the whitelist."""
    with (world.path / 'whitelist.json').open() as whitelist:
        return json.load(whitelist)

@api.util2.json_route(application, '/server/players')
def api_player_ids():
    """Returns an array of all known player IDs (Wurstmineberg IDs and Minecraft UUIDs)"""
    return [str(player) for player in api.util2.Player.all()]

@api.util2.json_route(application, '/server/sessions/lastseen')
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

@api.util2.json_route(application, '/server/worlds')
def api_worlds():
    """Returns an object mapping existing world names to short status summaries (like those returned by /world/&lt;world&gt;/status.json but without the lists of online players)"""
    return {world.name: api.util2.short_world_status(world) for world in minecraft.worlds()}
