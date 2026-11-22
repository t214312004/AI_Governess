"""Restore the approved v11 face objects in a PSD2Live v3.6.7 gesture checkpoint."""
import hashlib
import json
import struct
import zipfile


def project_rig(project):
    index, = [name for name in project.namelist() if name.startswith('rig/revisions/')]
    rig = json.loads(project.read(index))
    header = rig['header']
    if (header['format'], header['version'], header['build']) != ('psd2live-authored-rig', 1, '3.6.7'):
        raise ValueError('The authored rig format does not match PSD2Live v3.6.7')
    return index, rig


def object_path(digest):
    return f'rig/objects/{digest}.bin'


def object_ids(project, kind, digests):
    result = {}
    for digest in digests:
        data = project.read(object_path(digest))
        if data[:8] != b'PRIO\0\0\0\6' or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f'Invalid authored rig object {digest}')
        offset = 12 if kind == 'meshes' else 16
        size, = struct.unpack_from('>I', data, offset)
        identifier = data[offset + 4:offset + 4 + size].decode('utf-8')
        if identifier in result:
            raise ValueError(f'Duplicate rig ID: {identifier}')
        result[identifier] = digest
    return result


def preserve_face(baseline, draft, output):
    with zipfile.ZipFile(baseline) as original, zipfile.ZipFile(draft) as working:
        _, face = project_rig(original)
        checkpoint, gesture = project_rig(working)
        updates = {}
        for kind in ('meshes', 'deformers'):
            approved = object_ids(original, kind, face[kind])
            new = object_ids(working, kind, gesture[kind])
            if approved.keys() - new.keys():
                raise ValueError(f'Gesture draft is missing original {kind}')
            new.update(approved)
            gesture[kind] = list(new.values())
            for digest in approved.values():
                path = object_path(digest)
                if path not in working.namelist():
                    updates[path] = original.read(path)
        for key in ('pages', 'layers'):
            for identifier, value in face['header'][key].items():
                if gesture['header'][key][identifier] != value:
                    raise ValueError(f'Gesture draft changed the face atlas binding for {identifier}')
        gesture['header']['bounds'].update(face['header']['bounds'])
        updates[checkpoint] = json.dumps(gesture, separators=(',', ':')).encode()

        manifest = json.loads(working.read('manifest.json'))
        manifest['files'].update({path: hashlib.sha256(data).hexdigest() for path, data in updates.items()})
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=2) as merged:
            for name in working.namelist():
                if name != 'manifest.json' and name not in updates:
                    merged.writestr(name, working.read(name))
            for name, data in updates.items():
                merged.writestr(name, data)
            merged.writestr('manifest.json', json.dumps(manifest, separators=(',', ':')))
