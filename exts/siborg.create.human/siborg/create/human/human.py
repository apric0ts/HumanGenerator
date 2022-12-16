from typing import Tuple
from .mhcaller import MHCaller
import numpy as np
import omni.kit
import omni.usd
from pxr import Sdf, Usd, UsdGeom, UsdSkel
from .shared import sanitize
from .skeleton import Skeleton

class Human:
    def __init__(self, name='human', **kwargs):
        """Constructs an instance of Human.

        Parameters
        ----------
        name : str
            Name of the human. Defaults to 'human'
        """

        self.name = name

        # Create a skeleton object for the human
        self.skeleton = Skeleton()

        # Set the human in makehuman to default values
        MHCaller.reset_human()

    @property
    def objects(self):
        """List of objects attached to the human. Fetched from the makehuman app"""
        return MHCaller.objects

    def add_to_scene(self):
        """Adds the human to the scene. Creates a prim for the human with custom attributes
        to hold modifiers and proxies. Also creates a prim for each proxy and attaches it to
        the human prim.

        Returns
        -------
        str
            Path to the human prim"""

        # Get the current stage
        stage = omni.usd.get_context().get_stage()

        root_path = "/"

        # Get default prim.
        default_prim = stage.GetDefaultPrim()
        if default_prim.IsValid():
            # Set the rootpath under the stage's default prim, if the default prim is valid
            root_path = default_prim.GetPath().pathString

        # Create a path for the next available prim
        prim_path = omni.usd.get_stage_next_free_path(stage, root_path + "/" + self.name, False)

        # Create a prim for the human
        # Prim should be a SkelRoot so we can rig the human with a skeleton later
        UsdSkel.Root.Define(stage, prim_path)

        # Write the properties of the human to the prim
        self.write_properties(prim_path, stage)

        # Add the skeleton to the scene
        self.skeleton.add_to_stage(stage, prim_path)

        # Import makehuman objects into the scene
        self.import_meshes(prim_path, stage)

        return prim_path

    def update_in_scene(self, prim_path: str):
        """Updates the human in the scene. Writes the properties of the human to the
        human prim and imports the human and proxy meshes. This is called when the
        human is updated"""

        # Get the current stage
        stage = omni.usd.get_context().get_stage()

        # Write the properties of the human to the prim
        self.write_properties(prim_path, stage)

        # Import makehuman objects into the scene
        self.import_meshes(prim_path, stage)

    def import_meshes(self, prim_path: str, stage: Usd.Stage, offset: Tuple[float, float, float] = (0, 0, 0)):
        """Imports the meshes of the human into the scene. This is called when the human is
        added to the scene, and when the human is updated. This function creates mesh prims
        for both the human and its proxies, and attaches them to the human prim. If a mesh already
        exists in the scene, its values are updated instead of creating a new mesh.

        Parameters
        ----------
        prim_path : str
            Path to the human prim
        stage : Usd.Stage
            Stage to write to
        offset : Tuple[float, float, float]
            Offset to apply to the human and proxies. Defaults to (0, 0, 0)

        Returns
        -------
        paths : array of: Sdf.Path
            Usd Sdf paths to geometry prims in the scene
        """

        # Get the objects of the human from mhcaller
        objects = MHCaller.objects
        meshes = [o.mesh for o in objects]

        usd_mesh_paths = []

        for mesh in meshes:
            # Number of vertices per face
            nPerFace = mesh.vertsPerFaceForExport
            # Lists to hold pruned lists of vertex and UV indices
            newvertindices = []
            newuvindices = []

            # Array of coordinates organized [[x1,y1,z1],[x2,y2,z2]...]
            # Adding the given offset moves the mesh relative to the prim origin
            coords = mesh.getCoords() + offset
            for fn, fv in enumerate(mesh.fvert):
                if not mesh.face_mask[fn]:
                    continue
                # only include <nPerFace> verts for each face, and order them
                # consecutively
                newvertindices += [(fv[n]) for n in range(nPerFace)]
                fuv = mesh.fuvs[fn]
                # build an array of (u,v)s for each face
                newuvindices += [(fuv[n]) for n in range(nPerFace)]

            # Type conversion
            newvertindices = np.array(newvertindices)

            # Create mesh prim at appropriate path. Does not yet hold any data
            name = sanitize(mesh.name)
            usd_mesh_path = prim_path + "/" + name
            usd_mesh_paths.append(usd_mesh_path)
            # Check to see if the mesh prim already exists
            prim = stage.GetPrimAtPath(usd_mesh_path)

            if prim.IsValid():
                # omni.kit.commands.execute("DeletePrims", paths=[usd_mesh_path])
                point_attr = prim.GetAttribute('points')
                point_attr.Set(coords)

                face_count = prim.GetAttribute('faceVertexCounts')
                nface = [nPerFace] * int(len(newvertindices) / nPerFace)
                face_count.Set(nface)

                face_idx = prim.GetAttribute('faceVertexIndices')
                face_idx.Set(newvertindices)

                normals_attr = prim.GetAttribute('normals')
                normals_attr.Set(mesh.getNormals())

                meshGeom = UsdGeom.Mesh(prim)

            # If it doesn't exist, make it. This will run the first time a human is created
            else:
                meshGeom = UsdGeom.Mesh.Define(stage, usd_mesh_path)

                # Set vertices. This is a list of tuples for ALL vertices in an unassociated
                # cloud. Faces are built based on indices of this list.
                #   Example: 3 explicitly defined vertices:
                #   meshGeom.CreatePointsAttr([(-10, 0, -10), (-10, 0, 10), (10, 0, 10)]
                meshGeom.CreatePointsAttr(coords)

                # Set face vertex count. This is an array where each element is the number
                # of consecutive vertex indices to include in each face definition, as
                # indices are given as a single flat list. The length of this list is the
                # same as the number of faces
                #   Example: 4 faces with 4 vertices each
                #   meshGeom.CreateFaceVertexCountsAttr([4, 4, 4, 4])

                nface = [nPerFace] * int(len(newvertindices) / nPerFace)
                meshGeom.CreateFaceVertexCountsAttr(nface)

                # Set face vertex indices.
                #   Example: one face with 4 vertices defined by 4 indices.
                #   meshGeom.CreateFaceVertexIndicesAttr([0, 1, 2, 3])
                meshGeom.CreateFaceVertexIndicesAttr(newvertindices)

                # Set vertex normals. Normals are represented as a list of tuples each of
                # which is a vector indicating the direction a point is facing. This is later
                # Used to calculate face normals
                #   Example: Normals for 3 vertices
                # meshGeom.CreateNormalsAttr([(0, 1, 0), (0, 1, 0), (0, 1, 0), (0, 1,
                # 0)])

                meshGeom.CreateNormalsAttr(mesh.getNormals())
                meshGeom.SetNormalsInterpolation("vertex")

            # Set vertex uvs. UVs are represented as a list of tuples, each of which is a 2D
            # coordinate. UV's are used to map textures to the surface of 3D geometry
            #   Example: texture coordinates for 3 vertices
            #   texCoords.Set([(0, 1), (0, 0), (1, 0)])

            texCoords = meshGeom.CreatePrimvar(
                "st", Sdf.ValueTypeNames.TexCoord2fArray, UsdGeom.Tokens.faceVarying
            )
            texCoords.Set(mesh.getUVs(newuvindices))

            # # Subdivision is set to none. The mesh is as imported and not further refined
            meshGeom.CreateSubdivisionSchemeAttr().Set("none")

        # ConvertPath strings to USD Sdf paths. TODO change to map() for performance
        paths = [Sdf.Path(mesh_path) for mesh_path in usd_mesh_paths]

        return paths

    def write_properties(self, prim_path: str, stage: Usd.Stage):
        """Writes the properties of the human to the human prim. This includes modifiers and
        proxies. This is called when the human is added to the scene, and when the human is
        updated

        Parameters
        ----------
        prim_path : str
            Path to the human prim
        stage : Usd.Stage
            Stage to write to
        """

        prim = stage.GetPrimAtPath(prim_path)

        # Add custom data to the prim by key, designating the prim is a human
        prim.SetCustomDataByKey("human", True)

        # Get the modifiers of the human in mhcaller
        modifiers = MHCaller.modifiers

        for m in modifiers:
            # Add the modifier to the prim as custom data by key. For modifiers,
            # the format is "group/modifer:value"
            prim.SetCustomDataByKey("Modifiers:" + m.fullName, m.getValue())

        # Get the proxies of the human in mhcaller
        proxies = MHCaller.proxies

        for p in proxies:
            # Add the proxy to the prim as custom data by key under "Proxies".
            # Proxy type should be "proxymeshes" if type cannot be determined from the
            # proxy.type property.
            type = p.type if p.type else "proxymeshes"

            # Only "proxymeshes" and "clothes" should be subdictionaries of "Proxies"
            if type == "clothes" or type == "proxymeshes":
                prim.SetCustomDataByKey("Proxies:" + type + ":" + p.name, p.file)

            # Other proxy types should be added as a key to the prim with their
            # type as the key and the path as the value
            else:
                prim.SetCustomDataByKey("Proxies:" + type, p.file)

    def set_prim(self, usd_prim):
        """Updates the human based on the given prim's attributes

        Parameters
        ----------
        usd_prim : Usd.Prim
            Prim from which to update the human model."""

        # Get the data from the prim
        humandata = usd_prim.GetCustomData()

        # Get the modifiers from the prim
        modifiers = humandata.get("Modifiers")
        for m, v in modifiers.items():
            MHCaller.human.getModifier(m).setValue(v, skipDependencies=False)

        # Get the proxies from the prim
        proxies = humandata.get("Proxies")

        # Make sure the proxies are not empty
        if proxies:
            for type, path in proxies.items():
                # If the proxy type is not "proxymeshes" or "clothes", add it
                # as a proxy with the type as the type
                if type != "proxymeshes" and type != "clothes":
                    MHCaller.add_proxy(path, type)
                else:
                    # Add every proxy in the "clothes" or "proxymeshes" subdictionary
                    # In this case, name is unused
                    for name, path in proxies[type].items():
                        MHCaller.add_proxy(path, type)
        # TODO Proxy list is not updated in the UI
        # TODO this is slow, and should be optimized

        # Update the human in MHCaller
        MHCaller.human.applyAllTargets()
