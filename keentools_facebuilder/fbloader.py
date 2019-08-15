# ##### BEGIN GPL LICENSE BLOCK #####
# KeenTools for blender is a blender addon for using KeenTools in Blender.
# Copyright (C) 2019  KeenTools

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
# ##### END GPL LICENSE BLOCK #####
import bpy
import logging

import numpy as np

from . utils import manipulate
from . viewport import FBViewport
from . utils import attrs
from . utils import coords
from . utils.other import (
    FBStopTimer
)
from . builder import UniBuilder
from . fbdebug import FBDebug
from . config import Config, get_main_settings, BuilderType
from pykeentools import UnlicensedException


class FBLoader:
    # Builder selection: FaceBuilder or BodyBuilder
    builder = UniBuilder(Config.default_builder)
    viewport = FBViewport()

    @classmethod
    def update_cam_image_size(cls, cam_item):
        cam_item.update_image_size()

    @classmethod
    def update_camera_params(cls, head):
        """ Update when some camera parameters changes """
        logger = logging.getLogger(__name__)
        logger.debug("UPDATE CAMERA PARAMETERS")

        settings = get_main_settings()
        scene = bpy.context.scene

        # Check scene consistency
        heads_deleted, cams_deleted = settings.fix_heads()

        headnum = -1
        for i, h in enumerate(settings.heads):
            if head == h:
                headnum = i

        if headnum < 0:
            return

        rx = scene.render.resolution_x
        ry = scene.render.resolution_y

        # NoneBuilder for auto-select builder class
        fb = cls.new_builder(BuilderType.NoneBuilder, head.mod_ver)
        cls.load_only(headnum)

        max_index = -1
        max_pins = -1
        for i, c in enumerate(head.cameras):
            kid = c.keyframe_id
            cls.set_camera_projection(
                head.focal, head.sensor_width, rx, ry)
            # We are looking for keyframe that has maximum pins
            if c.pins_count > 0:
                if max_pins < c.pins_count:
                    max_index = kid
                    max_pins = c.pins_count
            c.camobj.data.lens = head.focal
            c.camobj.data.sensor_width = head.sensor_width
            c.camobj.data.sensor_height = head.sensor_height

        if cls.get_builder_type() == BuilderType.FaceBuilder:
            fb.set_auto_rigidity(settings.check_auto_rigidity)
            fb.set_rigidity(settings.rigidity)

        if max_index >= 0:
            try:
                # Solver
                fb.solve_for_current_pins(max_index)
                logger.debug("SOLVED {}".format(max_index))

            except UnlicensedException:
                settings.force_out_pinmode = True
                settings.license_error = True

        # Head Mesh update
        coords.update_head_mesh(fb, head.headobj)
        if settings.pinmode:
            cls.fb_redraw(headnum, settings.current_camnum)
        cls.update_cameras(headnum)
        cls.save_only(headnum)

    @classmethod
    def get_builder(cls):
        return cls.builder.get_builder()

    @classmethod
    def new_builder(cls, builder_type=BuilderType.NoneBuilder,
                    ver=Config.unknown_mod_ver):
        return cls.builder.new_builder(builder_type, ver)

    @classmethod
    def get_builder_type(cls):
        return cls.builder.get_builder_type()

    @classmethod
    def get_builder_version(cls):
        return cls.builder.get_version()

    @classmethod
    def set_keentools_version(cls, obj):
        attrs.set_keentools_version(obj, cls.get_builder_type(),
                                    cls.get_builder_version())

    @classmethod
    def out_pinmode(cls, headnum, camnum):
        logger = logging.getLogger(__name__)
        settings = get_main_settings()
        cls.viewport.unregister_handlers()
        cls.fb_save(headnum, camnum)
        # cls.viewport.wireframer.unregister_handler()
        headobj = settings.heads[headnum].headobj
        # Mark object by ver.
        cls.set_keentools_version(headobj)
        # Show geometry
        headobj.hide_set(False)
        settings.pinmode = False

        cls.viewport.current_pin = None
        manipulate.show_all_cameras(headnum)
        # === Debug use only ===
        FBDebug.add_event_to_queue('OUT_PIN_MODE', (0, 0))
        FBDebug.output_event_queue()
        FBDebug.clear_event_queue()
        # === Debug use only ===
        FBStopTimer.stop()
        logger.debug("STOPPER STOP")
        logger.debug("OUT PINMODE")

    @classmethod
    def save_only(cls, headnum):
        fb = cls.get_builder()
        settings = get_main_settings()
        head = settings.heads[headnum]
        # Save block
        head.set_serial_str(fb.serialize())

    @classmethod
    def save_camera(cls, headnum, camnum):
        fb = cls.get_builder()
        scene = bpy.context.scene
        settings = get_main_settings()
        cam = settings.heads[headnum].cameras[camnum]
        kid = manipulate.keyframe_by_camnum(headnum, camnum)

        cam.set_model_mat(fb.model_mat(kid))
        cam.set_frame_size(
            scene.render.resolution_x,
            scene.render.resolution_y)

    @classmethod
    def fb_save(cls, headnum, camnum):
        """ Face Builder Serialize Model Info """
        fb = cls.get_builder()
        scene = bpy.context.scene
        settings = get_main_settings()
        head = settings.heads[headnum]
        cam = head.cameras[camnum]

        # Save block
        head.set_serial_str(fb.serialize())

        kid = manipulate.keyframe_by_camnum(headnum, camnum)
        cam.set_model_mat(fb.model_mat(kid))
        # Save images list on headobj
        head.save_images_src()
        head.save_cam_settings()

    @classmethod
    def fb_redraw(cls, headnum, camnum):
        scene = bpy.context.scene
        fb = cls.get_builder()
        settings = get_main_settings()
        head = settings.heads[headnum]
        cam = head.cameras[camnum]
        headobj = head.headobj
        camobj = cam.camobj
        kid = manipulate.keyframe_by_camnum(headnum, camnum)
        # Camera update
        cls.place_cameraobj(kid, camobj, headobj)
        # Head Mesh update
        coords.update_head_mesh(fb, headobj)
        # Load pins from model
        cls.viewport.set_spins(cls.viewport.img_points(fb, kid))
        cls.viewport.update_surface_points(fb, headobj, kid)
        # Shader update
        cls.viewport.wireframer.init_geom_data(headobj)
        cls.viewport.wireframer.init_edge_indices(headobj)
        cls.viewport.wireframer.create_batches()

    @classmethod
    def update_cameras(cls, headnum):
        """ Update positions for all cameras """
        fb = cls.get_builder()
        settings = get_main_settings()
        head = settings.heads[headnum]
        headobj = head.headobj

        for i, cam in enumerate(head.cameras):
            camobj = cam.camobj
            if cam.pins_count > 0:
                # Camera update only if pins is present
                kid = manipulate.keyframe_by_camnum(headnum, i)
                cls.place_cameraobj(kid, camobj, headobj)
                cam.set_model_mat(fb.model_mat(kid))

    @classmethod
    def update_cam_image(cls, cam_item):
        """ Update camera background image """
        cam_data = cam_item.camobj.data
        cam_data.show_background_images = True

        if len(cam_data.background_images) == 0:
            b = cam_data.background_images.new()
        else:
            b = cam_data.background_images[0]

        b.image = cam_item.cam_image

        b.frame_method = 'CROP'
        b.show_on_foreground = False  # True
        b.alpha = 1.0  # 0.5

    # --------------------
    @classmethod
    def place_cameraobj(cls, keyframe, camobj, headobj):
        fb = cls.get_builder()
        mat = coords.calc_model_mat(
            fb.model_mat(keyframe),
            headobj.matrix_world
        )
        if mat is not None:
            camobj.matrix_world = mat

    @classmethod
    def set_camera_projection(cls, fl, sw, rx, ry,
                              near_clip=0.1, far_clip=1000.0):
        camera_w = rx  # Camera Width in pixels 1920
        camera_h = ry  # Camera Height in pixels 1080
        focal_length = fl
        sensor_width = sw
        fb = cls.get_builder()

        # This works only when Camera Sensor Mode is Auto
        if camera_w < camera_h:
            sensor_width = sw * camera_w / camera_h

        projection = coords.projection_matrix(
            camera_w, camera_h, focal_length, sensor_width,
            near_clip, far_clip)
        fb.set_projection_mat(projection)

    @classmethod
    def update_pins_count(cls, headnum, camnum):
        logger = logging.getLogger(__name__)
        settings = get_main_settings()
        head = settings.heads[headnum]
        cam = head.cameras[camnum]
        fb = cls.get_builder()
        kid = manipulate.keyframe_by_camnum(headnum, camnum)
        pins_count = fb.pins_count(kid)
        cam.pins_count = pins_count
        logger.debug("PINS_COUNT H:{} C:{} k:{} count:{}".format(
            headnum, camnum, kid, pins_count))

    @classmethod
    def get_next_keyframe(cls):
        fb = cls.get_builder()
        kfs = fb.keyframes()
        if kfs:
            return max(kfs) + 1
        return 1

    @classmethod
    def get_builder_mesh(cls, builder, mesh_name='keentools_mesh',
                         masks=(), uv_set='uv0'):
        for i, m in enumerate(masks):
            builder.set_mask(i, m)

        # change UV in accordance to selected UV set
        # Blender can't use integer as key in enum property
        builder.select_uv_set(0)
        if uv_set == 'uv1':
            builder.select_uv_set(1)
        if uv_set == 'uv2':
            builder.select_uv_set(2)
        if uv_set == 'uv3':
            builder.select_uv_set(3)

        geo = builder.applied_args_model()
        me = geo.mesh(0)

        v_count = me.points_count()
        vertices = []
        for i in range(0, v_count):
            vertices.append(me.point(i))

        rot = np.array([[1., 0., 0.], [0., 0., 1.], [0., -1., 0]])
        vertices2 = vertices @ rot
        # vertices2 = vertices

        f_count = me.faces_count()
        faces = []

        # Normals are not in use yet
        normals = []
        n = 0
        for i in range(0, f_count):
            row = []
            for j in range(0, me.face_size(i)):
                row.append(me.face_point(i, j))
                normal = me.normal(i, j) @ rot
                normals.append(tuple(normal))
                n += 1
            faces.append(tuple(row))

        mesh = bpy.data.meshes.new(mesh_name)
        mesh.from_pydata(vertices2, [], faces)

        # Init Custom Normals (work on Shading Flat!)
        # mesh.calc_normals_split()
        # mesh.normals_split_custom_set(normals)

        # Simple Shade Smooth analog
        values = [True] * len(mesh.polygons)
        mesh.polygons.foreach_set('use_smooth', values)

        uvtex = mesh.uv_layers.new()
        uvmap = uvtex.data
        # Fill uvs in uvmap
        uvs_count = me.uvs_count()
        for i in range(uvs_count):
            uvmap[i].uv = me.uv(i)

        mesh.update()

        # Warning! our autosmooth settings work on Shading Flat!
        # mesh.use_auto_smooth = True
        # mesh.auto_smooth_angle = 3.1415927410125732

        return mesh

    @classmethod
    def universal_mesh_loader(cls, builder_type, mesh_name='keentools_mesh',
                              masks=(), uv_set='uv0'):
        stored_builder_type = FBLoader.get_builder_type()
        stored_builder_version = FBLoader.get_builder_version()
        builder = cls.new_builder(builder_type, Config.unknown_mod_ver)

        mesh = cls.get_builder_mesh(builder, mesh_name, masks, uv_set)

        # Restore builder
        cls.new_builder(stored_builder_type, stored_builder_version)
        return mesh

    @classmethod
    def load_only(cls, headnum):
        logger = logging.getLogger(__name__)
        settings = get_main_settings()
        head = settings.heads[headnum]
        # Load serialized data
        fb = cls.get_builder()
        if not fb.deserialize(head.get_serial_str()):
            logger.warning('DESERIALIZE ERROR: {}'.format(
                head.get_serial_str()))

    @classmethod
    def load_all(cls, headnum, camnum, center=False):
        logger = logging.getLogger(__name__)
        scene = bpy.context.scene
        settings = get_main_settings()
        head = settings.heads[headnum]
        cam = head.cameras[camnum]
        camobj = cam.camobj
        headobj = head.headobj
        # end objects definition

        # Load serialized data
        fb = cls.get_builder()
        if not fb.deserialize(head.get_serial_str()):
            logger.warning('DESERIALIZE ERROR: {}'.format(
                head.get_serial_str()))

        # Check Scene consistency

        # Set projection matrix
        rx = scene.render.resolution_x
        ry = scene.render.resolution_y
        cls.set_camera_projection(head.focal, head.sensor_width, rx, ry)

        # Update all cameras model_mat
        for i, c in enumerate(head.cameras):
            kid = c.keyframe_id
            pins_count = fb.pins_count(kid)
            if pins_count == 0:
                if center or c.is_model_mat_empty():
                    fb.center_model_mat(kid)  # Center if no pins on camera
            else:
                fb.set_model_mat(kid, c.get_model_mat())

        kid = manipulate.keyframe_by_camnum(headnum, camnum)
        # Move current camera
        cls.place_cameraobj(kid, camobj, headobj)
        # Load pins from model
        cls.viewport.set_spins(cls.viewport.img_points(fb, kid))
        cls.viewport.current_pin = None
        logger.debug("LOAD MODEL END")

    @classmethod
    def add_camera(cls, headnum, img=None):
        logger = logging.getLogger(__name__)
        # scene = bpy.context.scene
        settings = get_main_settings()
        head = settings.heads[headnum]
        fb = cls.get_builder()

        # create camera data
        cam_data = bpy.data.cameras.new("fbCam")
        # create object camera data and insert the camera data
        cam_ob = bpy.data.objects.new("fbCamObj", cam_data)

        cam_ob.rotation_euler = [3.1415927410125732 * 0.5, 0, 0]
        camnum = len(head.cameras)

        cam_ob.location = [2 * camnum, -5 - headnum, 0.5]

        # place camera object to our list
        camera = head.cameras.add()
        camera.camobj = cam_ob

        num = cls.get_next_keyframe()
        # Create new keyframe
        fb.set_keyframe(num)
        camera.keyframe_id = num

        # link camera into scene
        col = attrs.get_obj_collection(head.headobj)
        if col is not None:
            col.objects.link(cam_ob)
        else:
            logger.error("ERROR IN COLLECTIONS")
            bpy.context.scene.collection.objects.link(cam_ob)  # Link to Scene

        # Add Background Image
        cam_data.display_size = 0.75  # Camera Size
        cam_data.lens = head.focal  # From Interface
        cam_data.sensor_width = head.sensor_width
        cam_data.sensor_height = head.sensor_height
        cam_data.show_background_images = True

        if len(cam_data.background_images) == 0:
            b = cam_data.background_images.new()
        else:
            b = cam_data.background_images[0]

        if img is not None:
            b.image = img
            settings.heads[headnum].cameras[camnum].cam_image = img
        # b.image = settings.heads[headnum].cameras[camnum].cam_image
        b.frame_method = 'CROP'
        b.show_on_foreground = False  # True
        b.alpha = 1.0  # 0.5

        # scene.update()  # Removed from API
        return camera

    @classmethod
    def add_camera_image(cls, headnum, img_path):
        img = bpy.data.images.load(img_path)
        cam_ob = cls.add_camera(headnum, img)
        return img
