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
        self.utm_zone, self.utm_hemisphere = self.calc_utm_zone()
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

        utm_zone = None
        utm_hemisphere = None

        try:
            arcpy.AddMessage('reading spatial reference of {}...'.format(self.name))
            #if self.info.spatialReference.type == 'Geographic':

            #    x_min = self.info.Extent.XMin
            #    x_max = self.info.Extent.XMax
            #    lon = x_min + (x_max - x_min) / 2

            #    y_min = self.info.Extent.YMin
            #    y_max = self.info.Extent.YMax
            #    lat = y_min + (y_max - y_min) / 2

            #elif self.info.spatialReference.type == 'Projected':
            #    lon = self.info.spatialReference.centralMeridianInDegrees

            x_min = self.info.Extent.XMin
            x_max = self.info.Extent.XMax
            lon = x_min + (x_max - x_min) / 2
            
            y_min = self.info.Extent.YMin
            y_max = self.info.Extent.YMax
            lat = y_min + (y_max - y_min) / 2

            utm_zone = int((lon + 180.0) / 6) + 1

            if lat < 0:
                utm_hemisphere = 'S'
            elif lat > 0:
                utm_hemisphere = 'N'
            else:
                utm_hemisphere = None

        except Exception as e:
            arcpy.AddWarning('unable to calculate UTM zone for {}'.format(self.name))
            arcpy.AddWarning('(The shp probably has an unknown spatial reference.)')
            utm_zone = 'unknown'
            utm_hemisphere = 'unknown'

        finally:
            return utm_zone, utm_hemisphere

    def get_utm_zone_epsg(self):
        try:
            utm_zone = '{}{}'.format(self.utm_zone, self.utm_hemisphere)
            utm_zone_epsg = epsg_codes_WGS84UTM[utm_zone][0]
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

        arcpy.AddMessage('------------------- TOTAL LENGTHS -------------------')
        df = self.results_df.groupby(['shp_path']).agg(self.agg_logic).round(self.fields_to_round)
        df = df[[f for f in self.fields if f in ['shp_name', 'utm_zone', 'length_sm', 'length_nm']]]
        df.index = df.shp_name
        df = df.drop(['shp_name'], axis=1)
        with pd.option_context('display.max_rows', None, 'display.max_columns', None):
            arcpy.AddMessage(df)
        arcpy.AddMessage('-----------------------------------------------------')

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
    #epsg_codes_NAD83UTM = {
    #    '1N': (6330, 'NAD_1983_2011_UTM_Zone_1N'),
    #    '2N': (6331, 'NAD_1983_2011_UTM_Zone_2N'),
    #    '3N': (6332, 'NAD_1983_2011_UTM_Zone_3N'),
    #    '4N': (6333, 'NAD_1983_2011_UTM_Zone_4N'),
    #    '5N': (6334, 'NAD_1983_2011_UTM_Zone_5N'),
    #    '6N': (6335, 'NAD_1983_2011_UTM_Zone_6N'),
    #    '7N': (6336, 'NAD_1983_2011_UTM_Zone_7N'),
    #    '8N': (6337, 'NAD_1983_2011_UTM_Zone_8N'),
    #    '9N': (6338, 'NAD_1983_2011_UTM_Zone_9N'),
    #    '10N': (6339, 'NAD_1983_2011_UTM_Zone_10N'),
    #    '11N': (6340, 'NAD_1983_2011_UTM_Zone_11N'),
    #    '12N': (6341, 'NAD_1983_2011_UTM_Zone_12N'),
    #    '13N': (6342, 'NAD_1983_2011_UTM_Zone_13N'),
    #    '14N': (6343, 'NAD_1983_2011_UTM_Zone_14N'),
    #    '15N': (6344, 'NAD_1983_2011_UTM_Zone_15N'),
    #    '16N': (6345, 'NAD_1983_2011_UTM_Zone_16N'),
    #    '17N': (6346, 'NAD_1983_2011_UTM_Zone_17N'),
    #    '18N': (6347, 'NAD_1983_2011_UTM_Zone_18N'),
    #    '19N': (6348, 'NAD_1983_2011_UTM_Zone_19N'),
    #    '20N': (102045, 'NAD_1983_2011_UTM_Zone_20N'),
    #    '59N': (6328, 'NAD_1983_2011_UTM_Zone_59N'),
    #    '60N': (6329, 'NAD_1983_2011_UTM_Zone_60N'),
    #}

    epsg_codes_WGS84UTM = {
        '10N': (32610, 'WGS_1984_UTM_Zone_10N'),
        '10S': (32710, 'WGS_1984_UTM_Zone_10S'),
        '11N': (32611, 'WGS_1984_UTM_Zone_11N'),
        '11S': (32711, 'WGS_1984_UTM_Zone_11S'),
        '12N': (32612, 'WGS_1984_UTM_Zone_12N'),
        '12S': (32712, 'WGS_1984_UTM_Zone_12S'),
        '13N': (32613, 'WGS_1984_UTM_Zone_13N'),
        '13S': (32713, 'WGS_1984_UTM_Zone_13S'),
        '14N': (32614, 'WGS_1984_UTM_Zone_14N'),
        '14S': (32714, 'WGS_1984_UTM_Zone_14S'),
        '15N': (32615, 'WGS_1984_UTM_Zone_15N'),
        '15S': (32715, 'WGS_1984_UTM_Zone_15S'),
        '16N': (32616, 'WGS_1984_UTM_Zone_16N'),
        '16S': (32716, 'WGS_1984_UTM_Zone_16S'),
        '17N': (32617, 'WGS_1984_UTM_Zone_17N'),
        '17S': (32717, 'WGS_1984_UTM_Zone_17S'),
        '18N': (32618, 'WGS_1984_UTM_Zone_18N'),
        '18S': (32718, 'WGS_1984_UTM_Zone_18S'),
        '19N': (32619, 'WGS_1984_UTM_Zone_19N'),
        '19S': (32719, 'WGS_1984_UTM_Zone_19S'),
        '1N': (32601, 'WGS_1984_UTM_Zone_1N'),
        '1S': (32701, 'WGS_1984_UTM_Zone_1S'),
        '20N': (32620, 'WGS_1984_UTM_Zone_20N'),
        '20S': (32720, 'WGS_1984_UTM_Zone_20S'),
        '21N': (32621, 'WGS_1984_UTM_Zone_21N'),
        '21S': (32721, 'WGS_1984_UTM_Zone_21S'),
        '22N': (32622, 'WGS_1984_UTM_Zone_22N'),
        '22S': (32722, 'WGS_1984_UTM_Zone_22S'),
        '23N': (32623, 'WGS_1984_UTM_Zone_23N'),
        '23S': (32723, 'WGS_1984_UTM_Zone_23S'),
        '24N': (32624, 'WGS_1984_UTM_Zone_24N'),
        '24S': (32724, 'WGS_1984_UTM_Zone_24S'),
        '25N': (32625, 'WGS_1984_UTM_Zone_25N'),
        '25S': (32725, 'WGS_1984_UTM_Zone_25S'),
        '26N': (32626, 'WGS_1984_UTM_Zone_26N'),
        '26S': (32726, 'WGS_1984_UTM_Zone_26S'),
        '27N': (32627, 'WGS_1984_UTM_Zone_27N'),
        '27S': (32727, 'WGS_1984_UTM_Zone_27S'),
        '28N': (32628, 'WGS_1984_UTM_Zone_28N'),
        '28S': (32728, 'WGS_1984_UTM_Zone_28S'),
        '29N': (32629, 'WGS_1984_UTM_Zone_29N'),
        '29S': (32729, 'WGS_1984_UTM_Zone_29S'),
        '2N': (32602, 'WGS_1984_UTM_Zone_2N'),
        '2S': (32702, 'WGS_1984_UTM_Zone_2S'),
        '30N': (32630, 'WGS_1984_UTM_Zone_30N'),
        '30S': (32730, 'WGS_1984_UTM_Zone_30S'),
        '31N': (32631, 'WGS_1984_UTM_Zone_31N'),
        '31S': (32731, 'WGS_1984_UTM_Zone_31S'),
        '32N': (32632, 'WGS_1984_UTM_Zone_32N'),
        '32S': (32732, 'WGS_1984_UTM_Zone_32S'),
        '33N': (32633, 'WGS_1984_UTM_Zone_33N'),
        '33S': (32733, 'WGS_1984_UTM_Zone_33S'),
        '34N': (32634, 'WGS_1984_UTM_Zone_34N'),
        '34S': (32734, 'WGS_1984_UTM_Zone_34S'),
        '35N': (32635, 'WGS_1984_UTM_Zone_35N'),
        '35S': (32735, 'WGS_1984_UTM_Zone_35S'),
        '36N': (32636, 'WGS_1984_UTM_Zone_36N'),
        '36S': (32736, 'WGS_1984_UTM_Zone_36S'),
        '37N': (32637, 'WGS_1984_UTM_Zone_37N'),
        '37S': (32737, 'WGS_1984_UTM_Zone_37S'),
        '38N': (32638, 'WGS_1984_UTM_Zone_38N'),
        '38S': (32738, 'WGS_1984_UTM_Zone_38S'),
        '39N': (32639, 'WGS_1984_UTM_Zone_39N'),
        '39S': (32739, 'WGS_1984_UTM_Zone_39S'),
        '3N': (32603, 'WGS_1984_UTM_Zone_3N'),
        '3S': (32703, 'WGS_1984_UTM_Zone_3S'),
        '40N': (32640, 'WGS_1984_UTM_Zone_40N'),
        '40S': (32740, 'WGS_1984_UTM_Zone_40S'),
        '41N': (32641, 'WGS_1984_UTM_Zone_41N'),
        '41S': (32741, 'WGS_1984_UTM_Zone_41S'),
        '42N': (32642, 'WGS_1984_UTM_Zone_42N'),
        '42S': (32742, 'WGS_1984_UTM_Zone_42S'),
        '43N': (32643, 'WGS_1984_UTM_Zone_43N'),
        '43S': (32743, 'WGS_1984_UTM_Zone_43S'),
        '44N': (32644, 'WGS_1984_UTM_Zone_44N'),
        '44S': (32744, 'WGS_1984_UTM_Zone_44S'),
        '45N': (32645, 'WGS_1984_UTM_Zone_45N'),
        '45S': (32745, 'WGS_1984_UTM_Zone_45S'),
        '46N': (32646, 'WGS_1984_UTM_Zone_46N'),
        '46S': (32746, 'WGS_1984_UTM_Zone_46S'),
        '47N': (32647, 'WGS_1984_UTM_Zone_47N'),
        '47S': (32747, 'WGS_1984_UTM_Zone_47S'),
        '48N': (32648, 'WGS_1984_UTM_Zone_48N'),
        '48S': (32748, 'WGS_1984_UTM_Zone_48S'),
        '49N': (32649, 'WGS_1984_UTM_Zone_49N'),
        '49S': (32749, 'WGS_1984_UTM_Zone_49S'),
        '4N': (32604, 'WGS_1984_UTM_Zone_4N'),
        '4S': (32704, 'WGS_1984_UTM_Zone_4S'),
        '50N': (32650, 'WGS_1984_UTM_Zone_50N'),
        '50S': (32750, 'WGS_1984_UTM_Zone_50S'),
        '51N': (32651, 'WGS_1984_UTM_Zone_51N'),
        '51S': (32751, 'WGS_1984_UTM_Zone_51S'),
        '52N': (32652, 'WGS_1984_UTM_Zone_52N'),
        '52S': (32752, 'WGS_1984_UTM_Zone_52S'),
        '53N': (32653, 'WGS_1984_UTM_Zone_53N'),
        '53S': (32753, 'WGS_1984_UTM_Zone_53S'),
        '54N': (32654, 'WGS_1984_UTM_Zone_54N'),
        '54S': (32754, 'WGS_1984_UTM_Zone_54S'),
        '55N': (32655, 'WGS_1984_UTM_Zone_55N'),
        '55S': (32755, 'WGS_1984_UTM_Zone_55S'),
        '56N': (32656, 'WGS_1984_UTM_Zone_56N'),
        '56S': (32756, 'WGS_1984_UTM_Zone_56S'),
        '57N': (32657, 'WGS_1984_UTM_Zone_57N'),
        '57S': (32757, 'WGS_1984_UTM_Zone_57S'),
        '58N': (32658, 'WGS_1984_UTM_Zone_58N'),
        '58S': (32758, 'WGS_1984_UTM_Zone_58S'),
        '59N': (32659, 'WGS_1984_UTM_Zone_59N'),
        '59S': (32759, 'WGS_1984_UTM_Zone_59S'),
        '5N': (32605, 'WGS_1984_UTM_Zone_5N'),
        '5S': (32705, 'WGS_1984_UTM_Zone_5S'),
        '60N': (32660, 'WGS_1984_UTM_Zone_60N'),
        '60S': (32760, 'WGS_1984_UTM_Zone_60S'),
        '6N': (32606, 'WGS_1984_UTM_Zone_6N'),
        '6S': (32706, 'WGS_1984_UTM_Zone_6S'),
        '7N': (32607, 'WGS_1984_UTM_Zone_7N'),
        '7S': (32707, 'WGS_1984_UTM_Zone_7S'),
        '8N': (32608, 'WGS_1984_UTM_Zone_8N'),
        '8S': (32708, 'WGS_1984_UTM_Zone_8S'),
        '9N': (32609, 'WGS_1984_UTM_Zone_9N'),
        '9S': (32709, 'WGS_1984_UTM_Zone_9S'),
    }

    main()
