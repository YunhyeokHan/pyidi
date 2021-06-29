import os
import numpy as np
import collections
import matplotlib.pyplot as plt
import pickle
import pyMRAW
import datetime
import json
import glob
import napari
from magicgui import magicgui

from .methods import IDIMethod, SimplifiedOpticalFlow, GradientBasedOpticalFlow, LucasKanadeSc, LucasKanade, LucasKanadeSc2
from . import tools
from . import selection

available_method_shortcuts = [
    ('sof', SimplifiedOpticalFlow),
    ('lk', LucasKanade),
    ('lk_scipy', LucasKanadeSc),
    ('lk_scipy2', LucasKanadeSc2)
    # ('gb', GradientBasedOpticalFlow)
    ]


class pyIDI:
    """
    The pyIDI base class represents the video to be analysed.
    """
    def __init__(self, cih_file):
        self.cih_file = cih_file
        if type(cih_file) == str:
            self.root = os.path.split(self.cih_file)[0]
        else:
            self.root = ''

        self.available_methods = dict([ 
            (key, {
                'IDIMethod': method,
                'description': method.__doc__,     
            })
            for key, method in available_method_shortcuts
        ])

        # Fill available methods into `set_method` docstring
        available_methods_doc = '\n' + '\n'.join([
            f"'{key}' ({method_dict['IDIMethod'].__name__}): {method_dict['description']}"
            for key, method_dict in self.available_methods.items()
            ])
        tools.update_docstring(self.set_method, added_doc=available_methods_doc)

        if type(cih_file) == str:
            # Load selected video
            self.mraw, self.info = pyMRAW.load_video(self.cih_file)
            self.N = self.info['Total Frame']
            self.image_width = self.info['Image Width']
            self.image_height = self.info['Image Height']
        
        elif type(cih_file) == np.ndarray:
            self.mraw = cih_file
            self.N = cih_file.shape[0]
            self.image_height = cih_file.shape[1]
            self.image_width = cih_file.shape[2]
            self.info = {}
        
        else:
            raise ValueError('`cih_file` must be either a cih filename or a 3D array (N_time, height, width)')


    def set_method(self, method, **kwargs):
        """
        Set displacement identification method on video.
        To configure the method, use `method.configure()`

        Available methods:
        ---
        [Available method names and descriptions go here.]
        ---

        :param method: the method to be used for displacement identification.
        :type method: IDIMethod or str
        """
        if isinstance(method, str) and method in self.available_methods.keys():
            self.method_name = method
            self.method = self.available_methods[method]['IDIMethod'](self, **kwargs)
        elif callable(method) and hasattr(method, 'calculate_displacements'):
            self.method_name = 'external_method'
            try:
                self.method = method(self, **kwargs)
            except:
                raise ValueError("The input `method` is not a valid `IDIMethod`.")
        else:
            raise ValueError("method must either be a valid name from `available_methods` or an `IDIMethod`.")
        
        # Update `get_displacements` docstring
        tools.update_docstring(self.get_displacements, self.method.calculate_displacements)
        # Update `show_points` docstring
        if hasattr(self.method, 'show_points'):
            try:
                tools.update_docstring(self.show_points, self.method.show_points)
            except:
                pass


    def set_points(self, points=None, method=None, **kwargs):
        """
        Set points that will be used to calculate displacements.
        If `points` is None and a `method` has aready been set on this `pyIDI` instance, 
        the `method` object's `get_point` is used to get method-appropriate points.
        """
        if points is None:
            if not hasattr(self, 'method'):
                if method is not None:
                    self.set_method(method)
                else:
                    raise ValueError("Invalid arguments. Please input points, or set the IDI method first.")
            self.method.get_points(self, **kwargs) # get_points sets the attribute video.points                
        else:
            self.points = np.asarray(points)


    def show_points(self, **kwargs):
        """
        Show selected points on image.
        """

        if hasattr(self, 'method') and hasattr(self.method, 'show_points'):
            self.method.show_points(self, **kwargs)
        else:
            figsize = kwargs.get('figsize', (15, 5))
            cmap = kwargs.get('cmap', 'gray')
            marker = kwargs.get('marker', '.')
            color = kwargs.get('color', 'r')
            fig, ax = plt.subplots(figsize=figsize)
            ax.imshow(self.mraw[0].astype(float), cmap=cmap)
            ax.scatter(self.points[:, 1], self.points[:, 0], 
                marker=marker, color=color)
            plt.grid(False)
            plt.show()


    def show_field(self, field, scale=1., width=0.5):
        """
        Show displacement field on image.
        
        :param field: Field of displacements (number_of_points, 2)
        :type field: ndarray
        :param scale: scale the field, defaults to 1.
        :param scale: float, optional
        :param width: width of the arrow, defaults to 0.5
        :param width: float, optional
        """
        max_L = np.max(field[:, 0]**2 + field[:, 1]**2)

        fig, ax = plt.subplots(1)
        ax.imshow(self.mraw[0], 'gray')
        for i, ind in enumerate(self.points):
            f0 = field[i, 0]
            f1 = field[i, 1]
            alpha = (f0**2 + f1**2) / max_L
            if alpha < 0.2:
                alpha = 0.2
            plt.arrow(ind[1], ind[0], scale*f1, scale*f0, width=width, color='r', alpha=alpha)


    def get_displacements(self, autosave=True, **kwargs):
        """
        Calculate the displacements based on chosen method.

        Method docstring:
        ---
        Method is not set. Please use the `set_method` method.
        ---
        """
        if hasattr(self, 'method'):
            self.method.calculate_displacements(self, **kwargs)
            self.displacements = self.method.displacements
            
            # auto-save and clearing temp files
            if hasattr(self.method, 'process_number'):
                if self.method.process_number == 0:
                    
                    if autosave:
                        self.create_analysis_directory()
                        self.save(root=self.root_this_analysis)

                    self.method.clear_temp_files()
                    
            return self.displacements
        else:
            raise ValueError('IDI method has not yet been set. Please call `set_method()` first.')


    def close_video(self):
        """
        Close the .mraw video memmap.
        """
        if hasattr(self, 'mraw'):
            self.mraw._mmap.close()
            del self.mraw
    

    def create_analysis_directory(self):
        cih_file_ = os.path.split(self.cih_file)[-1].split('.')[0]
        self.root_analysis = os.path.join(self.root, f'{cih_file_}_pyidi_analysis')
        if not os.path.exists(self.root_analysis):
            os.mkdir(self.root_analysis)
        
        analyses = glob.glob(os.path.join(self.root_analysis, 'analysis_*/'))
        if analyses:
            last_an = sorted(analyses)[-1]
            print(last_an, last_an.split('\\')[-2])
            n = int(last_an.split('\\')[-2].split('_')[-1])
        else:
            n = 0
        self.root_this_analysis = os.path.join(self.root_analysis, f'analysis_{n+1:0>3.0f}')
        
        os.mkdir(self.root_this_analysis)

    
    def save(self, root=''):
        pickle.dump(self.displacements, open(os.path.join(root, 'results.pkl'), 'wb'), protocol=-1)
        pickle.dump(self.points, open(os.path.join(root, 'points.pkl'), 'wb'), protocol=-1)

        out = {
            'info': self.info,
            'createdate': datetime.datetime.now().strftime("%Y %m %d    %H:%M:%S"),
            'cih_file': self.cih_file,
            'settings': self.method.create_settings_dict(),
            'method': self.method_name
        }

        with open(os.path.join(root, 'settings.txt'), 'w') as f:
            json.dump(out, f, sort_keys=True, indent=2)

    
    def __repr__(self):
        
        rep = 'File name: ' + self.cih_file + ',\n' + \
        'Image width: ' + str(self.image_width) + ',\n' + \
        'Image height: ' + str(self.image_height) + ',\n' + \
        'Total frame: ' + str(self.N) + ',\n' + \
        'Record Rate(fps): ' + str(self.info['Record Rate(fps)'])
        
        if hasattr(self, 'method_name'):
            rep +=',\n' +  'Method: ' + self.method_name
                
            if hasattr(self.method, 'subset_size'):
                rep += ',\n' + 'Subset size: ' + str(self.method.subset_size)
                
            elif hasattr(self.method, 'roi_size'):
                 rep += ',\n' + 'ROI size: ' + str(self.method.roi_size)

        
        if hasattr(self, 'points'):
             rep +=',\n' + 'Number of points: ' + str(len(self.points))

        return rep

    def __call__(self): #napari image viewer
        viewer = napari.Viewer()
        layer = viewer.add_image(self.mraw) #image layer

        def view_ROI(self): # view ROI boxes
            if hasattr(self.method, 'subset_size') or hasattr(self.method, 'roi_size'): #subset/roi layer
                

                if hasattr(self.method, 'subset_size'):
                   half_subset=self.method.subset_size/2
                elif hasattr(self.method, 'roi_size'):
                   half_subset=self.method.roi_size/2


                rectangles=np.empty(shape=(len(self.points),4,2))
                for i in range(len(self.points)):
                    rectangle=np.array([[self.points[i,0]-half_subset, self.points[i,1]-half_subset], \
                    [self.points[i,0]-half_subset, self.points[i,1]+half_subset], \
                    [self.points[i,0]+half_subset, self.points[i,1]+half_subset], \
                    [self.points[i,0]+half_subset, self.points[i,1]-half_subset]])
                   
                    rectangles[i,:,:]=rectangle
    
                shapes_layer = viewer.add_shapes(rectangles, shape_type='rectangle', edge_width=0.1, edge_color='coral', face_color='#4169e164', opacity=0.8,name='ROI box')
        
        if hasattr(self, 'points'): #if points are given, add points layer
            points_layer = viewer.add_points(self.points,size=1,edge_color='white', face_color='coral', symbol='cross')

            view_ROI(self) #add ROI layer
            viewer.layers['Points'].visible=False 

        else: #if there are no points given, launch point selector
            grid_layer=viewer.add_points(name='Points',size=1,face_color='coral',symbol='cross')
            shapes_deselect= viewer.add_shapes(name='Area Deselection',edge_color='white',face_color='#ffffff00')
            shapes= viewer.add_shapes(name='Area Selection',edge_color='white',face_color='#ffffff00')

            @magicgui( 
                call_button="Confirm selection",
                Overlap_pixels={'min': -100 })
            def widget_grid(
                Horizontal_ROI_size: int=5,
                Vertical_ROI_size: int=5,
                Overlap_pixels: int=0,
                Show_ROI_box: bool=False):

                if  viewer.layers['Area Selection'].data == []: #individual points selection
                    grid_points=np.round(viewer.layers['Points'].data).astype(int)
                
                else: #area selection
                    border=viewer.layers['Area Selection'].data[0].T #shape data
                        
                    if viewer.layers['Area Deselection'].data == []:
                        deselect_border=[[],[]]
                    else:     
                        deselect_border=viewer.layers['Area Deselection'].data[0].T #deselection shape data
                    
                    grid_points=selection.get_roi_grid(polygon_points=border,roi_size=(Vertical_ROI_size,Horizontal_ROI_size),noverlap=Overlap_pixels,deselect_polygon=deselect_border) #get grid points
                                    
                self.points=grid_points #export points data
                if 'ROI box' in viewer.layers:
                    viewer.layers.pop('ROI box') # refresh ROI layer
                
                if Show_ROI_box is True:
                    view_ROI(self) #Show ROI
                
                viewer.layers.pop('Points') #refresh grid layer
                viewer.add_points(grid_points,size=1,face_color='coral',symbol='cross',name='Points')

                if len(self.points)==0:
                    del self.points
                    
            viewer.window.add_dock_widget(widget_grid)
            
            