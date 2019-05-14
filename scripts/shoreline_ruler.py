"""
This script is designed to be run via the 'Shoreline Ruler' tool
in NOAA RSD's in-house ArcGIS toolbox RSD_Toolbox.tbx.


Author:
Nick Forfinski-Sarkozi
nick.forfinski-sarkozi@noaa.gov
"""


import os
import datetime
import numpy as np
import pandas as pd
import arcpy


class ShorelineFile:

    """An instance of this class is created for every shapefile a user specifies."""

    def __init__(self, shp_path):
        self.path = shp_path.replace('\'', '')
        self.name = self.path.split(os.sep)[-1]
        self.info = arcpy.Describe(self.path)
        self.utm_zone = self.calc_utm_zone()
        self.utm_zone_epsg = self.get_utm_zone_epsg()
        self.sr_to_use = arcpy.SpatialReference(self.utm_zone_epsg)
        self.shp_fields = self.get_shapefile_fields()
        self.has_ccoast = True if 'CLASS' in [f.name for f in self.shp_fields] else False
        self.results = []

    def get_shapefile_fields(self):
        try:
            fields = arcpy.ListFields(self.path)
        except Exception as e:
            arcpy.AddWarning('problem with getting fields from {}, moving on'.format(self.path))
            fields = []
        finally:
            return fields

    def calc_utm_zone(self):
        """This method calculates the UTM zone of the shapefile based on the
        longitude midpoint.  The shapefile is assumed to be in unprojected
        decimal degrees (NAD83).
        """

        try:
            arcpy.AddMessage('reading spatial reference of {}...'.format(self.name))
            if self.info.spatialReference.type == 'Geographic':
                x_min = self.info.Extent.XMin
                x_max = self.info.Extent.XMax
                lon = x_min + (x_max - x_min) / 2
            elif self.info.spatialReference.type == 'Projected':
                lon = self.info.spatialReference.centralMeridianInDegrees
            utm_zone = int((lon + 180.0) / 6) + 1
        except Exception as e:
            arcpy.AddWarning('unable to calculate UTM zone for {}'.format(self.name))
            arcpy.AddWarning('(The shp probably has an unknown spatial reference.)')
            utm_zone = 'unknown'
        finally:
            return utm_zone

    def get_utm_zone_epsg(self):
        try:
            utm_zone_epsg = int(epsg_codes[self.utm_zone][0])
        except Exception as e:
            utm_zone_epsg = None
        finally:
            return utm_zone_epsg

    def calc_lengths(self):
        """This method "calculates" the length of a feature by accessing 
        the SHAPE@LENGTH token of the features geometry object.  Although 
        the input spatial reference is assumed to be unprojected degress 
        (NAD83), the length is reported as per the spatial reference 
        referenced in the searchcursor.
        """

        if self.has_ccoast:
            cursor_fields = ['SHAPE@LENGTH', 'CLASS', 'OID@']
        else:
            cursor_fields = ['SHAPE@LENGTH', 'OID@']

        with arcpy.da.SearchCursor(self.path, cursor_fields, 
                                   spatial_reference=self.sr_to_use) as cursor:
            
            for row in cursor:
                if self.has_ccoast:
                    ccoast_class = row[1]
                else:
                    ccoast_class = 'none'

                # make sure length is a number (sometimes geometry is corrupt)
                if type(row[0]) is float:  
                    self.add_to_shp_results(ccoast_class, row[0])
                else:
                    arcpy.AddWarning(
                        '''unknown geometry error OID# {} ({})'''.format(row[-1], self.name))

    def add_to_shp_results(self, ccoast_class, length_m):
        """This method appends the current result (i.e. one feature's
        length, with additional meatadata) to the results for the entire 
        shapefile's result array.
        """
        length_sm = length_m / METERS_PER_US_STATUTE_MILE
        length_nm = length_m / METERS_PER_US_NAUTICAL_MILE

        note = ''

        result_info = (self.name, self.path, 
                       self.info.spatialReference.name, 
                       self.sr_to_use.name, self.utm_zone, ccoast_class, 
                       length_sm, length_nm, note, )

        self.results.append(result_info)
        

class ResultsTable:

    def __init__(self):
        self.results = []
        self.results_df = None
        self.groupby_fields = ['shp_path', 'ccoast_class']
        self.fields_to_round = {'length_sm': 2, 'length_nm': 2}
        self.table_name = arcpy.ValidateTableName(str(datetime.datetime.now())[0:19])
        self.table_path = os.path.join(arcpy.env.scratchGDB, 
                                       'ShorelineMileages_{}'.format(self.table_name))

        self.fields = ['shp_name', 'shp_path', 'shp_sr', 'calc_sr', 
                       'utm_zone', 'ccoast_class', 'length_sm', 'length_nm', 'notes']

        self.agg_logic = {'shp_sr': 'first', 
                          'shp_name': 'first', 
                          'calc_sr': 'first', 
                          'utm_zone': 'first', 
                          'length_sm': 'sum', 
                          'length_nm': 'sum',
                          'notes': 'first'}

    def add_shp_results(self, shp_results):
        """This method adds a shapefile's result table to the
        overall results table.
        """
        self.results.extend(shp_results)

    def display_summary_table(self):
        """This method displays two summary tables: 
        (1) the results grouped by shapefile and C-COAST class (i.e., lengths per class per shp)
        (2) the results grouped by shapefile (i.e., total lengths per shp)
        """
        self.results_df = pd.DataFrame(self.results, columns=self.fields)

        #arcpy.AddMessage('----- C-COAST CLASS LENGTHS -----')
        #class_grouped_df = self.results_df.groupby(self.groupby_fields).sum().round(self.fields_to_round)
        #arcpy.AddMessage(class_grouped_df)
        #arcpy.AddMessage('---------------------------------')

        arcpy.AddMessage('--------- TOTAL LENGTHS ---------')
        df = self.results_df.groupby(['shp_path']).agg(self.agg_logic).round(self.fields_to_round)
        df = df[[f for f in self.fields if f in ['shp_name', 'utm_zone', 'length_sm', 'length_nm']]]
        df.index = df.shp_name
        df = df.drop(['shp_name'], axis=1)
        with pd.option_context('display.max_rows', None, 'display.max_columns', None):
            arcpy.AddMessage(df)
        arcpy.AddMessage('---------------------------------')

    def export_to_table(self):
        """This method exports the overall results table (a Pandas DataFrame)
        to an ArcGIS table in the scratch geodatabase location (as specified
        in the arcpy.env.scratchGDB environment setting)
        """
        arcpy.AddMessage('exporting results to {}...'.format(self.table_path))

        df = self.results_df.groupby(self.groupby_fields, as_index=False).agg(self.agg_logic)
        df = df[self.fields]
        df = df.round(self.fields_to_round)

        x = np.array(np.rec.fromrecords(df.values))
        names = df.dtypes.index.tolist()
        x.dtype.names = tuple(names)
        arcpy.da.NumPyArrayToTable(x, self.table_path)

    def add_table_to_current_map(self):
        """This methods adds the (optional) detailed-results table to the CURRENT map."""
        arcpy.AddMessage('adding {} to CURRENT map...'.format(self.table_path))
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        table_view = arcpy.mapping.TableView(self.table_path)
        arcpy.mapping.AddTableView(df, table_view)
        arcpy.RefreshTOC()
        del mxd


def main():

    # get the user-specified tool settings
    shps = arcpy.GetParameterAsText(0).split(';')
    shp_dirs = arcpy.GetParameterAsText(1).split(';')
    include_subdirs = arcpy.GetParameterAsText(2)
    make_table = arcpy.GetParameterAsText(3)

    arcpy.AddMessage(shps)
    arcpy.AddMessage(shp_dirs)

    def gather_shps(shps, shp_dirs, include_subdirs):
        shps_to_process = []

        # add individual shp(s)
        if shps[0] is not '':
            for shp in shps:
                shps_to_process.append(shp)


        # identitfy shapefiles in specified directory(ies)
        if shp_dirs[0] is not '':
            arcpy.AddMessage('getting shapefiles in specified directory(ies)...')
            for shp_dir in shp_dirs:
                if include_subdirs:
                    for root, dirs, files in os.walk(shp_dir):
                        for f in files:
                            if f.endswith('.shp'): 
                                shp_path = os.path.join(root, f)
                                arcpy.AddMessage(shp_path)
                                shps_to_process.append(shp_path)
                else:
                    for f in os.listdir(shp_dir):
                        if f.endswith('.shp'):
                            shp_path = os.path.join(shp_dir, f)
                            arcpy.AddMessage(shp_path)
                            shps_to_process.append(shp_path)

        return shps_to_process

                    
    results = ResultsTable()

    shps = gather_shps(shps, shp_dirs, include_subdirs)

    if shps:
        for shp_path in shps:
            shp = ShorelineFile(shp_path)

            if shp.utm_zone_epsg is not None:
                if shp.info.shapeType == u'Polyline':
                    arcpy.AddMessage('processing {}...'.format(shp.path))
                    shp.calc_lengths()
                    results.add_shp_results(shp.results)
                else:
                    arcpy.AddWarning('''{} doesn\'t contain polylines'''.format(shp.path))
                    note = 'doesn\'t contain polylines'
                    shp_result = [(shp.name, shp.path, shp.info.spatialReference.name, 
                                    shp.sr_to_use.name, shp.utm_zone, 'none', 0, 0, note, )]
                    results.add_shp_results(shp_result)
            else:
                arcpy.AddWarning('''{} spatial reference unknown'''.format(shp.path))
                note = 'unknown spatial reference'
                shp_result = [(shp.name, shp.path, 'unknown', 'unknown', 'unknown', 
                                'none', None, None, note, )]
                results.add_shp_results(shp_result)
    
        results.display_summary_table()

        if make_table:
            results.export_to_table()
            results.add_table_to_current_map()
    else:
        arcpy.AddWarning('''
        No shapefiles were specified and/or contained 
        in the specified directory(ies).''')


if __name__ == "__main__":

    METERS_PER_US_STATUTE_MILE = 1609.3472186944
    METERS_PER_INT_STATUTE_MILE = 1609.344  # not used
    METERS_PER_US_NAUTICAL_MILE = 1852.

    # dict of EPSG codes
    epsg_codes = {
        1: ('6330', 'NAD_1983_2011_UTM_Zone_1N'),
        2: ('6331', 'NAD_1983_2011_UTM_Zone_2N'),
        3: ('6332', 'NAD_1983_2011_UTM_Zone_3N'),
        4: ('6333', 'NAD_1983_2011_UTM_Zone_4N'),
        5: ('6334', 'NAD_1983_2011_UTM_Zone_5N'),
        6: ('6335', 'NAD_1983_2011_UTM_Zone_6N'),
        7: ('6336', 'NAD_1983_2011_UTM_Zone_7N'),
        8: ('6337', 'NAD_1983_2011_UTM_Zone_8N'),
        9: ('6338', 'NAD_1983_2011_UTM_Zone_9N'),
        10: ('6339', 'NAD_1983_2011_UTM_Zone_10N'),
        11: ('6340', 'NAD_1983_2011_UTM_Zone_11N'),
        12: ('6341', 'NAD_1983_2011_UTM_Zone_12N'),
        13: ('6342', 'NAD_1983_2011_UTM_Zone_13N'),
        14: ('6343', 'NAD_1983_2011_UTM_Zone_14N'),
        15: ('6344', 'NAD_1983_2011_UTM_Zone_15N'),
        16: ('6345', 'NAD_1983_2011_UTM_Zone_16N'),
        17: ('6346', 'NAD_1983_2011_UTM_Zone_17N'),
        18: ('6347', 'NAD_1983_2011_UTM_Zone_18N'),
        19: ('6348', 'NAD_1983_2011_UTM_Zone_19N'),
        20: ('102045', 'NAD_1983_2011_UTM_Zone_20N'),
        59: ('6328', 'NAD_1983_2011_UTM_Zone_59N'),
        60: ('6329', 'NAD_1983_2011_UTM_Zone_60N'),
    }

    main()
