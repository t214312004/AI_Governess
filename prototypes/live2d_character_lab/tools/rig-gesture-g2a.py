"""Join the original gesture pieces to the v11 native project on WSL2."""
import hashlib
import json
import math
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from importlib import import_module

lab = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(lab / 'vendor'))
from mcp_proxy import Client

preserve_face = import_module('preserve-gesture-face').preserve_face

folder = lab / 'authoring/gesture-g2a'
base = lab / 'authoring/polish-v11/shared-face-rig-v11-polish.psd2live'
package = lab / '.cache/psd2live-linux-v3.6.7/PSD2Live-3.6.7-linux-x64.tar.gz'
source_sha = 'ac788290387ca5b373d445f9f879185de3b4102373487b389e3adab0e433b686'
spec = json.loads((lab / 'design/gesture-g2a.json').read_text(encoding='utf-8'))
parts = json.loads((folder / 'parts.json').read_text(encoding='utf-8'))
reach = 'ParamGestureReach'
lift = spec['motion']['lift']
chest = spec['chest']
variant = 'ParamGestureVariant'
flex = 'ParamGestureIndexFlex'
body_fit = 'ParamGestureBodyFit'
contact = 'ParamGestureContact'
support_pose = 'ParamGestureSupportSettle'
chest_fold = 'ParamGestureChestFold'
chin_support = 'ParamGestureChinSupport'
side_parameter = 'ParamGestureSide'
axis_x = spec['mirrorAxis'] - spec['coordinateOrigin'][0]
anthropometry = spec['handAnthropometry']
shoulder_span = anthropometry['shoulderMarkers'][1] - anthropometry['shoulderMarkers'][0]
forearm_length = shoulder_span * anthropometry['ansurForearmLengthMm'] / anthropometry['ansurShoulderBreadthMm']


def smoothstep(start, end, value):
    t = max(0, min(1, (value - start) / (end - start)))
    return t * t * (3 - 2 * t)


def turned(vector, angle):
    x, y = vector
    radians = math.radians(angle)
    c, s = math.cos(radians), math.sin(radians)
    return x * c - y * s, x * s + y * c


def difference(a, b):
    return tuple(x - y for x, y in zip(a, b))


def addition(a, b):
    return tuple(x + y for x, y in zip(a, b))


def at_length(vector, length):
    scale = length / math.hypot(*vector)
    return tuple(component * scale for component in vector)


def polar_angle(vector):
    return math.degrees(math.atan2(vector[1], vector[0]))


def interpolate(start, end, t):
    return start + (end - start) * t


def blend_displacements(start, end, t):
    def move(x, y):
        return tuple(interpolate(a, b, t) for a, b in zip(start(x, y), end(x, y)))
    return move


def arm_geometry(pose, target_wrist):
    wx, wy = pose['wrist']
    ex, ey = pose['elbow']
    tx, ty = target_wrist
    forearm = (wx - ex, wy - ey)
    target = (tx - ex, ty - ey)
    angle = math.degrees(math.atan2(target[1], target[0]) - math.atan2(forearm[1], forearm[0]))
    local = turned(target, -angle)
    return angle, forearm, (local[0] - forearm[0], local[1] - forearm[1])


def point_sleeve_adjustment(x, y):
    # Each pair records matching silhouette rows in the raised sleeve and reference.
    rows = spec['pointSleeveFit']['cuffRows']
    before, after = next(((a, b) for a, b in zip(rows, rows[1:]) if y <= b[0][0]), rows[-2:])
    t = max(0, min(1, (y - before[0][0]) / (after[0][0] - before[0][0])))
    source, target = [tuple(a + t * (b - a) for a, b in zip(start, end))
                      for start, end in zip(before, after)]
    span = max(0, min(1, (x - source[1]) / (source[2] - source[1])))
    left_delta, right_delta = target[1] - source[1], target[2] - source[2]
    return left_delta + span * (right_delta - left_delta), target[0] - source[0]


def offset_surface(target, key, topology, displacement):
    positions = {index: (x, y) for index, x, y in topology['items']}
    groups = defaultdict(list)
    for index, (x, y) in positions.items():
        dx, dy = displacement(x, y)
        delta = (round(dx, 2), round(dy, 2))
        if any(delta):
            groups[delta].append(index)
    changes = []
    offsets = list(groups.items())
    for start in range(0, len(offsets), 16):
        # PSD2Live normalizes each change against the input to that change.
        # Later groups must account for the points moved by earlier groups.
        xs, ys = zip(*positions.values())
        width, height = max(xs) - min(xs), max(ys) - min(ys)
        operations = []
        for (dx, dy), indices in offsets[start:start + 16]:
            operations.append(dict(type='translate', delta=[dx / width, dy / height], selection={'indices': indices}))
            for index in indices:
                x, y = positions[index]
                positions[index] = x + dx, y + dy
        changes.append(dict(target=target, key=key, operations=operations))
    return changes


def reference_elbow(pose, vertices, edges, cuff_displacement):
    ref = spec['forearm45']
    angle, (dx, dy), _ = arm_geometry(pose, spec['inbetween']['targetWrist'])
    rotation = -lift['startDegrees'] - math.degrees(math.atan2(dy, dx))
    coordinate = 1 - rotation / angle
    ex, ey = pose['elbow']
    ex -= spec['coordinateOrigin'][0]

    def project(x, y):
        ox, oy = cuff_displacement(x, y)
        bx, by = (1 - coordinate) * ox, (1 - coordinate) * oy
        px, py = turned((x + bx - ex, y + by - ey), rotation)
        return px + ex, py + ey

    projected = {index: project(x, y) for index, x, y in vertices['items']}
    source_x, source_y = ref['referenceElbow']
    target_x, target_y = ref['canvasElbow']
    scale = ref['scale']
    outline = [(target_x + (x - source_x) * scale - spec['coordinateOrigin'][0],
                target_y + (y - source_y) * scale) for x, y in ref['outerContour']]

    def outer_edge(y):
        crossings = []
        for first, second in edges:
            (x1, y1), (x2, y2) = projected[first], projected[second]
            if y1 != y2 and min(y1, y2) <= y <= max(y1, y2):
                crossings.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        return min(crossings, default=None)

    def target_edge(y):
        for (x1, y1), (x2, y2) in zip(outline, outline[1:]):
            if y1 <= y <= y2:
                return x1 + (y - y1) * (x2 - x1) / (y2 - y1)
        return outline[-1][0]

    def displacement(x, y):
        base_x, base_y = cuff_displacement(x, y)
        screen_x, screen_y = project(x, y)
        weight = smoothstep(1226, 1251, screen_y) * (1 - smoothstep(1279, 1312, screen_y))
        edge = outer_edge(screen_y) if weight else None
        correction = 0
        if edge is not None:
            lateral = 1 - smoothstep(7, 58, screen_x - edge)
            # Calibrate the outline to the sleeve; retain the curve's smooth turn.
            correction = max(-20, min(15, target_edge(screen_y) - edge)) * weight * lateral
        ox, oy = turned((correction, 0), -rotation)
        return base_x * (1 - coordinate) + ox, base_y * (1 - coordinate) + oy

    return coordinate, displacement


def rig(client, project):
    client.edit('project_open', path=str(base), discard_unsaved=True)
    atlas = client.call('atlas_get')[0]
    layers = client.call('workspace_inspect', dict(scope='layers', query='SharedSkinContinuous', limit=64))[0]['items']
    skin, = [item for item in layers if item['name'] == 'SharedSkinContinuous']
    client.edit('layer_replace_image', layer_id=skin['id'], path=str(folder / 'SharedSkinGesture.png'),
                rebuild_mesh=False)
    meshes = {}
    for name, rect in parts.items():
        client.edit('layer_import_images', paths=[str(folder / (name + '.png'))])
        objects = client.call('workspace_inspect', dict(scope='objects', query=name, limit=64))[0]['items']
        meshes[name], = [item['target'] for item in objects if item['target'].startswith('mesh:')]
        layers = client.call('workspace_inspect', dict(scope='layers', query=name, limit=64))[0]['items']
        layer, = [item for item in layers if item['name'] == name]
        client.edit('layer_set_canvas_rect', layer_id=layer['id'], rect=rect)
        print(f'Imported {name}: {meshes[name]}', flush=True)

    for identifier, label, maximum, neutral in [
            (reach, 'Shared forearm path', chest['motion']['keyStart'] + 1, 1),
            (flex, 'Right index fingertip flex', 1, 0), (chest_fold, 'Chest hand curl', 1, 0)]:
        client.edit('parameter_create', parameter_id=identifier, name=label, min=0, max=maximum, default=neutral)
    client.edit('parameter_create', parameter_id=variant, name='Hand shape', min=-1, max=1, default=0)
    client.edit('parameter_create', parameter_id=support_pose, name='Supporting hand pose', min=-1, max=1, default=0)
    client.edit('parameter_create', parameter_id=contact, name='Supporting fingers contact', min=-1, max=1, default=0)
    client.edit('parameter_create', parameter_id=chin_support, name='Elbow support alignment', min=-1, max=1, default=1)
    client.edit('parameter_create', parameter_id=body_fit, name='Upper sleeve contour', min=-2, max=1, default=-1)

    client.edit('parameter_create', parameter_id=side_parameter, name='Active arm side', min=0, max=1, default=0)
    calibrated_sides = []
    for side in (0, 1):
        suffix = 'Left' if side else ''
        local_meshes = {name.removesuffix(suffix): handle for name, handle in meshes.items()
                        if name.endswith('Left') == bool(side)}
        calibrated_sides.append(rig_side(client, local_meshes, side))
    print('Authored both elbows, wrists and localized index flex.', flush=True)
    result = client.call('atlas_get')[0]
    updated_tiles = {tile['layer_id']: tile for tile in result['tiles']}
    if atlas['budget'] != result['budget'] or any(
        updated_tiles.get(tile['layer_id']) != tile for tile in atlas['tiles']
    ):
        raise RuntimeError('The gesture layers changed the placement of existing texture tiles')
    client.edit('project_save_as', path=str(project))
    (folder / 'runtime-map.json').write_text(json.dumps(meshes, indent=2), encoding='utf-8')
    (folder / 'arm-fit.json').write_text(json.dumps(
        {'shoulderSpan': shoulder_span, 'forearmLength': forearm_length, 'sides': calibrated_sides}, indent=2) + '\n',
        encoding='utf-8')



def rig_side(client, meshes, side):
    changes = []
    sign = -1 if side else 1
    suffix = 'Left' if side else 'Right'

    def reflect(x):
        return 2 * axis_x - x if side else x

    def opacity(name, key, value):
        target = meshes[name]
        for active in (0, 1):
            coordinate = {**key, side_parameter: active}
            changes.append(dict(op='seed', target=target, key=coordinate))
            changes.append(dict(op='set', target=target, key=coordinate,
                                channels={'opacity': value if active == side else 0}))

    def canonical_surface(surface):
        return {**surface, 'items': [(i, reflect(x), y) for i, x, y in surface['items']]}

    def offsets(name, key, surface, move):
        def reflected_move(x, y):
            dx, dy = move(reflect(x), y)
            return sign * dx, dy
        return offset_surface(name, key, surface, reflected_move)

    draw_orders = {
        'GestureBody': 1, 'GestureUpperSleeve': 2, 'GesturePassiveShoulder': 2,
        'GestureElbowUnderlay': 3, 'GestureChestSleeveBridge': 3,
        'GestureSupportBack': 875, 'GestureForearm': 880, 'GestureCuff': 881,
        'GesturechinHand': 882, 'GestureindexHand': 882, 'GestureChestHand': 882, 'GestureSupportChin': 890,
        'GestureSupport': 890, 'GestureSupportFingers': 891,
    }
    for name, order in draw_orders.items():
        client.edit('layer_draw_order', target=meshes[name], order=order)
    for name in ('GesturePassiveShoulder', 'GestureUpperSleeve', 'GestureCuff', 'GestureForearm'):
        opacity(name, {}, 1)
    for fit in (-1, 0, 1):
        opacity('GestureBody', {chin_support: fit}, 1)

    for value in (-1, 0, 1):
        for hand_name, hand_pose in [('GestureChestHand', -1), ('GesturechinHand', 0), ('GestureindexHand', 1)]:
            if hand_name == 'GestureChestHand':
                for fold in (0, 1):
                    opacity(hand_name, {variant: value, chest_fold: fold}, int(value == hand_pose))
            else:
                opacity(hand_name, {variant: value}, int(value == hand_pose))
        opacity('GestureSupport', {support_pose: value}, int(value == 1))
        for overlap in (-1, 0, .22, .86, 1):
            key = {support_pose: value, contact: overlap}
            for fit in (0, 1):
                shape = {**key, chin_support: fit}
                opacity('GestureSupportChin', shape, int(value == 0 and overlap <= .22))
            opacity('GestureSupportBack', key, int(value == -1 or (value == 0 and overlap > 0)))
            opacity('GestureSupportFingers', key, int(value == -1 or (value == 0 and overlap >= .86)))
        for overlap in (0, 1):
            for fit in (0, 1):
                opacity('GestureElbowUnderlay', {support_pose: value, contact: overlap, chin_support: fit},
                        int(value >= 0 and overlap == 0))
        opacity('GestureChestSleeveBridge', {support_pose: value}, int(value == -1))

    upper = meshes['GestureUpperSleeve']
    pose = spec['chin']
    cuff, forearm, hand = (meshes[name] for name in ('GestureCuff', 'GestureForearm', 'GesturechinHand'))

    def topology(target):
        return client.call('mesh_get_topology', dict(target=target, limit=4096))[0]

    cuff_surface = topology(cuff)
    cuff_edges = client.call('mesh_get_topology', dict(target=cuff, section='outline', limit=4096))[0]['items']

    low_angle, (fx, fy), low_offset = arm_geometry(pose, spec['inbetween']['targetWrist'])
    point = spec['index']
    hinge_shift = difference(point['elbow'], pose['elbow'])
    high_angle, _, high_offset = arm_geometry(pose, difference(point['wrist'], hinge_shift))
    local_hinge_shift = turned(hinge_shift, -high_angle)
    chin_palm, point_palm = pose['palmLandmarks'], point['palmLandmarks']
    chin_axis = difference(chin_palm['knuckles'], chin_palm['wrist'])
    point_axis = difference(point_palm['knuckles'], point_palm['wrist'])
    palm_rotation = math.degrees(math.atan2(point_axis[1], point_axis[0]) - math.atan2(chin_axis[1], chin_axis[0]))
    high_wrist_angle = palm_rotation - high_angle
    high_skin_offset = difference(
        turned(difference(point_palm['wrist'], point['wrist']), -palm_rotation),
        difference(chin_palm['wrist'], pose['wrist']),
    )
    elbow_at_45 = -lift['startDegrees'] - math.degrees(math.atan2(fy, fx))
    angle45 = 1 - elbow_at_45 / low_angle
    wrist_at_45 = (1 - angle45) * pose['lowerWristAngle']
    lift_samples = [(lift['keyStart'] + t, t) for t in lift['samples']]

    ex, ey = pose['elbow']
    ex -= spec['coordinateOrigin'][0]
    wy = pose['wrist'][1]

    def cuff_displacement(offset, pivot_move=(0, 0)):
        def move(x, y):
            distance = ((x - ex) * fx + (y - ey) * fy) / (fx * fx + fy * fy)
            weight = max(0, min(1, (distance - .1) / .73))
            return tuple(weight * value + translation for value, translation in zip(offset, pivot_move))
        return move

    def hand_displacement(offset, wrist_angle, skin_offset):
        sx, sy = turned(offset, -wrist_angle)
        def move(x, y):
            depth = max(0, min(1, (wy - y) / (wy - pose['anatomicalWristY'])))
            return sx + depth * skin_offset[0], sy + depth * skin_offset[1]
        return move

    cuff_low = cuff_displacement(low_offset)
    _, elbow45 = reference_elbow(pose, canonical_surface(cuff_surface), cuff_edges, cuff_low)
    skin_low = hand_displacement(low_offset, pose['lowerWristAngle'], (0, pose['lowerForearmOffset']))
    palm_high = hand_displacement(tuple(a + b for a, b in zip(high_offset, local_hinge_shift)),
                                  high_wrist_angle, high_skin_offset)
    skin_at_45 = blend_displacements(skin_low, lambda x, y: (0, 0), angle45)
    sleeve_registration = spec['pointSleeveFit']
    viewport = sleeve_registration['viewport']
    scale = viewport['pixels'] / viewport['size']
    high_cuff = cuff_displacement(high_offset, local_hinge_shift)

    def raised_cuff(x, y):
        dx, dy = high_cuff(x, y)
        rx, ry = turned((x + dx - ex, y + dy - ey), high_angle)
        px = (ex + rx - viewport['left']) * scale
        py = (ey + ry - viewport['top']) * scale
        fit_x, fit_y = point_sleeve_adjustment(px, py)
        offset_x, offset_y = turned((fit_x / scale, fit_y / scale), -high_angle)
        return dx + offset_x, dy + offset_y

    wx = pose['wrist'][0] - spec['coordinateOrigin'][0]

    def raised_skin(x, y):
        dx, dy = palm_high(x, y)
        rx, ry = turned((x + dx - wx, y + dy - wy), high_wrist_angle)
        _, elbow_y = turned((rx + wx - ex, ry + wy - ey), high_angle)
        py = (ey + elbow_y - viewport['top']) * scale
        weight = smoothstep(*sleeve_registration['skinBlendY'], py)
        offset_x, offset_y = turned(tuple(weight * d / scale for d in sleeve_registration['skinCuffOffset']), -palm_rotation)
        return dx + offset_x, dy + offset_y

    wrist_x, wrist_y = chin_palm['wrist']
    wrist_x -= spec['coordinateOrigin'][0]

    def project_wrist(move, elbow_angle, wrist_angle):
        dx, dy = move(wrist_x, wrist_y)
        x, y = turned((wrist_x + dx - wx, wrist_y + dy - wy), wrist_angle)
        return turned((wx + x - ex, wy + y - ey), elbow_angle)

    # Use the elbow and wrist of the fitted pointing endpoint to define the arc.
    # These coordinates are relative to the elbow in the unposed artwork.
    arc_center = turned(raised_cuff(ex, ey), high_angle)
    point_wrist = project_wrist(palm_high, high_angle, high_wrist_angle)
    arc_radius = at_length(difference(point_wrist, arc_center), forearm_length)
    point_shift = difference(addition(arc_center, arc_radius), point_wrist)
    chin_wrist = (wrist_x - ex, wrist_y - ey)
    chin_center = difference(chin_wrist, at_length(chin_wrist, forearm_length))
    chest_center = difference(chest['elbow'], pose['elbow'])
    chest_art_wrist = difference(chest['palmLandmarks']['wrist'], pose['elbow'])
    chest_ray = at_length(difference(chest_art_wrist, chest_center), forearm_length)
    chest_shift = difference(addition(chest_center, chest_ray), chest_art_wrist)
    chest_angle = polar_angle(chest_ray) - polar_angle((fx, fy))
    chest_wrist_angle = 14
    chest_samples = [(chest['motion']['keyStart'] + t, t) for t in lift['samples']]

    def rebase_pivot(move, elbow_angle, wrist_angle=0):
        offset = difference(arc_center, turned(arc_center, -elbow_angle))
        dx, dy = turned(offset, -wrist_angle)

        def rebased(x, y):
            sx, sy = move(x, y)
            return sx + dx, sy + dy

        return rebased

    for origin, identifier, targets, angles in [
        ((ex + arc_center[0], ey + arc_center[1]), 'GestureElbow' + suffix,
         [cuff, forearm, hand], (low_angle, elbow_at_45, high_angle, chest_angle)),
        ((wx, wy), 'GestureWrist' + suffix,
         [forearm, hand], (pose['lowerWristAngle'], wrist_at_45, high_wrist_angle, chest_wrist_angle)),
    ]:
        x, y = origin
        client.edit('canvas_rotation', id=identifier, name=identifier,
                    meshes=[t.removeprefix('mesh:') for t in targets], add_to='parent_of_selected',
                    origin=[reflect(x), y], angle=0, preservePose=True)
        low, start, end, chest_end = angles
        angle_keys = [(0, low), (1, 0)]
        angle_keys.extend((key, interpolate(start, end, t)) for key, t in lift_samples)
        angle_keys.extend((key, interpolate(low, chest_end, t)) for key, t in chest_samples)
        for value, angle in angle_keys:
            target = 'rotation:' + identifier
            changes.append(dict(op='seed', target=target, key={reach: value}))
            changes.append(dict(op='set', target=target, key={reach: value},
                                geometry={'angle': sign * angle, 'scale': 1}))
    for start in range(0, len(changes), 100):
        client.edit('keyform_apply', changes=changes[start:start + 100])

    def fitted_arm(cuff_move, skin_move, palm_move, elbow_angle, wrist_angle, center, wrist, sleeve_follow=0):
        wrist_shift = difference(wrist, project_wrist(palm_move, elbow_angle, wrist_angle))
        elbow_shift = difference(center, turned(cuff_move(ex, ey), elbow_angle))
        share = lift['cuffShare']
        cuff_shift = tuple(interpolate(a, b, share) for a, b in zip(elbow_shift, wrist_shift))
        cuff_offset = cuff_displacement(turned(cuff_shift, -elbow_angle))
        proximal_offset = turned(elbow_shift, -elbow_angle)
        skin_offset = turned(cuff_shift, -elbow_angle - wrist_angle)
        palm_offset = turned(wrist_shift, -elbow_angle - wrist_angle)

        def move_cuff(x, y):
            span = ((x - ex) * fx + (y - ey) * fy) / (fx * fx + fy * fy)
            proximal = 1 - smoothstep(.1, .6, span)
            # Keep the outer elbow contour while aligning the joint inside the sleeve.
            inside = interpolate(1 - smoothstep(28, 65, abs(x - ex)), 1, sleeve_follow)
            return tuple(a + b + proximal * inside * c
                         for a, b, c in zip(cuff_move(x, y), cuff_offset(x, y), proximal_offset))

        def move_skin(x, y):
            depth = max(0, min(1, (wy - y) / (wy - wrist_y)))
            return tuple(a + interpolate(b, c, depth)
                         for a, b, c in zip(skin_move(x, y), skin_offset, palm_offset))

        def move_palm(x, y):
            return tuple(a + b for a, b in zip(palm_move(x, y), palm_offset))

        return (rebase_pivot(move_cuff, elbow_angle),
                rebase_pivot(move_skin, elbow_angle, wrist_angle),
                rebase_pivot(move_palm, elbow_angle, wrist_angle))

    cuff_forms, skin_forms, hand_forms = {}, {}, {}
    radius_at_45 = turned(arc_radius, elbow_at_45 - high_angle)
    for key, t in lift_samples:
        elbow_angle = interpolate(elbow_at_45, high_angle, t)
        wrist_angle = interpolate(wrist_at_45, high_wrist_angle, t)
        cuff_forms[key], skin_forms[key], hand_forms[key] = fitted_arm(
            blend_displacements(elbow45, raised_cuff, t),
            blend_displacements(skin_at_45, raised_skin, t),
            blend_displacements(skin_at_45, palm_high, t),
            elbow_angle, wrist_angle, arc_center, addition(arc_center, turned(arc_radius, elbow_angle - high_angle)))

    low_wrist_angle = pose['lowerWristAngle']
    low_wrist = project_wrist(skin_low, low_angle, low_wrist_angle)
    radius_angle_at_45 = polar_angle(radius_at_45)

    def neutral(x, y):
        return 0, 0

    # Use the same anatomical length throughout the shared lowering/raising path.
    for from_key, to_key, from_center, to_center, from_radial, to_radial, from_cuff, to_cuff, from_skin, to_skin in [
        (0, angle45, (0, 0), arc_center, polar_angle(low_wrist), radius_angle_at_45,
         cuff_low, elbow45, skin_low, skin_at_45),
        (angle45, 1, arc_center, chin_center, radius_angle_at_45, polar_angle(chin_wrist),
         elbow45, neutral, skin_at_45, neutral),
    ]:
        for t in lift['sharedSamples']:
            key = interpolate(from_key, to_key, t)
            if key == angle45:
                continue
            center = tuple(interpolate(a, b, t) for a, b in zip(from_center, to_center))
            wrist = addition(center, turned((forearm_length, 0), interpolate(from_radial, to_radial, t)))
            skin = blend_displacements(from_skin, to_skin, t)
            cuff_forms[key], skin_forms[key], hand_forms[key] = fitted_arm(
                blend_displacements(from_cuff, to_cuff, t), skin, skin,
                (1 - key) * low_angle, (1 - key) * low_wrist_angle,
                center, wrist, sleeve_follow=t if from_key else 0)
    for forms in (cuff_forms, skin_forms, hand_forms):
        forms[angle45] = forms[lift['keyStart']]

    # The chest route departs from the same crossed-arm key and keeps the fitted length.
    for key, t in chest_samples:
        elbow_angle = interpolate(low_angle, chest_angle, t)
        wrist_angle = interpolate(low_wrist_angle, chest_wrist_angle, t)
        center = tuple(t * component for component in chest_center)
        wrist = addition(center, turned((forearm_length, 0),
                         interpolate(polar_angle(low_wrist), polar_angle(chest_ray), t)))
        skin = blend_displacements(skin_low, neutral, t)
        cuff_forms[key], skin_forms[key], hand_forms[key] = fitted_arm(
            blend_displacements(cuff_low, neutral, t), skin, skin,
            elbow_angle, wrist_angle, center, wrist, sleeve_follow=t)

    keys = []
    deformations = []
    chest_grip_shift = chest['supportGripShift']

    def support_shift(follow):
        vector = chin_center if follow >= 0 else chest_grip_shift
        return tuple(abs(follow) * component for component in vector)

    def upper_move(fit, follow):
        dx, dy = support_shift(follow)

        def move(x, y):
            vertical = smoothstep(799, 899, y) * (1 - .65 * smoothstep(1179, 1257, y))
            lateral = 1 - smoothstep(825, 919, x + spec['coordinateOrigin'][0])
            shoulder_x = max(-1, fit) * round(12 * vertical * lateral) / 2
            if fit == -2:
                shoulder_x -= 26 * smoothstep(835, 1190, y) * lateral
            elbow_weight = smoothstep(1120, 1270, y)
            return shoulder_x + elbow_weight * dx, elbow_weight * dy
        return move

    upper_surface = topology(upper)
    bridge = meshes['GestureChestSleeveBridge']
    bridge_surface = topology(bridge)
    for fit in (-2, -1, 0, 1):
        for follow in (-1, 0, 1):
            key = {body_fit: fit, chin_support: follow, side_parameter: side}
            keys.append(dict(op='seed', target=upper, key=key))
            deformations.extend(offsets(upper, key, upper_surface, upper_move(fit, follow)))
            bridge_key = {**key, support_pose: -1}
            keys.append(dict(op='seed', target=bridge, key=bridge_key))
            deformations.extend(offsets(bridge, bridge_key, bridge_surface, upper_move(fit, follow)))

    for name, parameter_keys in [
        ('GestureSupportChin', [({support_pose: 0, contact: overlap, chin_support: 1}, 1)
                                for overlap in (0, .22)]),
        ('GestureSupportBack', [({support_pose: -1, contact: overlap}, overlap) for overlap in (-1, .22, .86, 1)]),
        ('GestureSupportFingers', [({support_pose: -1, contact: overlap}, overlap) for overlap in (-1, .22, .86, 1)]),
        ('GestureElbowUnderlay', [({support_pose: pose, contact: 0, chin_support: 1}, 1) for pose in (0, 1)]),
        ('GestureBody', [({chin_support: follow}, follow) for follow in (-1, 1)]),
    ]:
        target = meshes[name]
        surface = topology(target)

        def track_elbow(x, y):
            weight = 1 - smoothstep(925, 1190, x + spec['coordinateOrigin'][0])
            if name in ('GestureElbowUnderlay', 'GestureBody'):
                # Carry the painted arm backing with the separate support hand.
                weight *= smoothstep(1170, 1240, y) * (1 - smoothstep(1390, 1440, y))
            return tuple(weight * component for component in shift)

        for parameters, follow in parameter_keys:
            shift = support_shift(follow)
            key = {**parameters, side_parameter: side}
            deformations.extend(offsets(target, key, surface, track_elbow))
    for name, surface, parameter, forms in [
        (cuff, cuff_surface, None, cuff_forms),
        (forearm, topology(forearm), None, skin_forms),
        (hand, topology(hand), variant, hand_forms),
    ]:
        for visible in ((-1, 0, 1) if parameter else (None,)):
            for angle, move in forms.items():
                key = {reach: angle, side_parameter: side}
                if parameter:
                    key[parameter] = visible
                keys.append(dict(op='seed', target=name, key=key))
                if move:
                    deformations.extend(offsets(name, key, surface, move))
    point_hand = meshes['GestureindexHand']
    point_surface = topology(point_hand)
    items = point_surface['items']
    top = min(y for _, _, y in items)
    height = max(y for _, _, y in items) - top
    # The finger anchors are in source pixels so trimming the wrist cannot move them.
    root_y, tip_y, limit_y = ((y - top) / height for y in (742, 615, 747))
    chest_hand = meshes['GestureChestHand']
    chest_surface = topology(chest_hand)
    chest_xs = [x for _, x, _ in chest_surface['items']]
    chest_ys = [y for _, _, y in chest_surface['items']]
    chest_wx, chest_wy = chest['palmLandmarks']['wrist']
    chest_pivot = [
        (reflect(chest_wx - spec['coordinateOrigin'][0]) - min(chest_xs)) / (max(chest_xs) - min(chest_xs)),
        (chest_wy - min(chest_ys)) / (max(chest_ys) - min(chest_ys)),
    ]
    chest_kx, chest_ky = chest['palmLandmarks']['knuckles']
    knuckle_pivot = [
        (reflect(chest_kx - spec['coordinateOrigin'][0]) - min(chest_xs)) / (max(chest_xs) - min(chest_xs)),
        (chest_ky - min(chest_ys)) / (max(chest_ys) - min(chest_ys)),
    ]
    fingers_only = {'rect': [0, 0, .62, .37] if side else [.38, 0, 1, .37], 'feather': .17}
    distal_hand = {'rect': [0, 0, 1, .48], 'feather': .19}
    for value in (-1, 0, 1):
        for fold in (0, 1):
            chest_key = {variant: value, chest_fold: fold, side_parameter: side}
            deformations.extend(offsets(chest_hand, chest_key, chest_surface, lambda x, y: chest_shift))
            if fold:
                deformations.append(dict(target=chest_hand, key=chest_key, operations=[
                    dict(type='scale', factors=[.74, .78], pivot=knuckle_pivot, selection=fingers_only),
                    dict(type='rotate', degrees=-sign * 17, pivot=chest_pivot, selection=distal_hand),
                ]))
        for bend in (0, 1):
            key = {variant: value, flex: bend, side_parameter: side}
            keys.append(dict(op='seed', target=point_hand, key=key))
            deformations.extend(offsets(point_hand, key, point_surface, lambda x, y: point_shift))
        deformations.append(dict(target=meshes['GestureindexHand'], key={variant: value, flex: 1, side_parameter: side}, operations=[
            dict(type='arc', degrees=sign * 52,
                 root=[.47 if side else .53, root_y], tip=[.67 if side else .33, tip_y], root_pin=.17,
                 selection={'rect': [.24, 0, .88, limit_y] if side else [.12, 0, .76, limit_y], 'feather': .12}),
        ]))
    for start in range(0, len(keys), 100):
        client.edit('keyform_apply', changes=keys[start:start + 100])
    for start in range(0, len(deformations), 100):
        client.edit('rig_deform', changes=deformations[start:start + 100])
    return {'chinElbowShift': [sign * chin_center[0], chin_center[1]],
            'pointWristShift': [sign * point_shift[0], point_shift[1]],
            'chestWristShift': [sign * chest_shift[0], chest_shift[1]]}


def export(client, project, output):
    client.edit('project_open', path=str(project), discard_unsaved=True)
    result = client.edit('project_export_model', output_directory=str(output))
    (output / 'export-warnings.json').write_text(json.dumps(result['warnings'], indent=2), encoding='utf-8')
    print(f"Exported {len(result['files'])} files from the reopened project.", flush=True)


def main():
    with package.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != source_sha:
            raise RuntimeError('Unexpected Linux package SHA-256')
    with tempfile.TemporaryDirectory(prefix='psd2live-gesture-') as temp:
        work = Path(temp)
        subprocess.run(['tar', '-xf', str(package), '-C', temp], check=True)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        token = secrets.token_hex(32)
        command = [str(work/'PSD2Live/bin/PSD2Live'), 'mcp', '--port', str(port),
                   '--token', token, '--store', str(work/'store')]
        log_path = work/'tool.log'
        with log_path.open('wb') as log:
            process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
            try:
                for attempt in range(60):
                    if process.poll() is not None:
                        raise RuntimeError(log_path.read_text(errors='replace').replace(token, '[redacted]'))
                    try:
                        with socket.create_connection(('127.0.0.1', port), timeout=1):
                            break
                    except OSError:
                        time.sleep(.5)
                else:
                    raise RuntimeError('Linux rig service did not start')
                draft = work / 'gesture-draft.psd2live'
                project = lab / '.cache/gesture-g2a-candidate.psd2live'
                output = lab / '.cache/gesture-face-candidate'
                with Client(endpoint=f'http://127.0.0.1:{port}/mcp', token=token) as client:
                    rig(client, draft)
                    preserve_face(base, draft, project)
                    export(client, project, output)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    main()
