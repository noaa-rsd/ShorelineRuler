"""
This script is designed to be run via the 'Shoreline Ruler' tool
in NOAA RSD's in-house ArcGIS toolbox RSD_Toolbox.tbx.

General script workflow:


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
        self.shp_path = shp_path
        self.shp_name = self.shp_path.split(os.sep)[-1]
        self.info = arcpy.Describe(self.shp_path)
        self.utm_zone = self.calc_utm_zone()
        self.utm_zone_epsg = int(epsg_codes[self.utm_zone][0])
        self.sr_to_use = arcpy.SpatialReference(self.utm_zone_epsg)
        self.shp_fields = arcpy.ListFields(self.shp_path)
        self.has_ccoast = True if 'CLASS' in [f.name for f in self.shp_fields] else False
        self.results = []

    def calc_utm_zone(self):
        """This method calculates the UTM zone of the shapefile based on the
        longitude midpoint.  The shapefile is assumed to be in unprojected
        decimal degrees (NAD83).
        """

        if self.info.spatialReference.type == 'Geographic':
            x_min = self.info.Extent.XMin
            x_max = self.info.Extent.XMax
            lon = x_min + (x_max - x_min) / 2
        elif self.info.spatialReference.type == 'Projected':
            lon = self.info.spatialReference.centralMeridianInDegrees
        utm_zone = int(lon + 180.0) / 6 + 1
        return utm_zone

    def calc_lengths(self):
        """This method "calculates" the length of a feature by accessing the SHAPE@LENGTH 
        token of the features geometry object.  Although the input spatial reference
        is assumed to be unprojected degress (NAD83), the length is reported as 
        per the spatial reference referenced in the searchcursor.
        """

        if self.has_ccoast:
            cursor_fields = ['SHAPE@LENGTH', 'CLASS', 'OID@']
        else:
            cursor_fields = ['SHAPE@LENGTH', 'OID@']

        with arcpy.da.SearchCursor(self.shp_path, cursor_fields, 
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
                        '''unknown geometry error OID# 
                        {} ({}), moving on...'''.format(row[-1], self.shp_name))

    def add_to_shp_results(self, ccoast_class, length_m):
        """This method appends the current result (i.e. one feature's
        length, with additional meatadat) to the results for the entire 
        shapefile's result array.
        """
        length_sm = length_m / METERS_PER_US_STATUTE_MILE
        length_nm = length_m / METERS_PER_US_NAUTICAL_MILE

        result_info = (self.shp_name, self.shp_path, 
                       self.info.spatialReference.name, self.sr_to_use.name,
                       ccoast_class, length_sm, length_nm, )

        self.results.append(result_info)
        

class ResultsTable:

    def __init__(self):
        self.results = []
        self.results_df = None
        self.groupby_fields = ['shp_name', 'ccoast_class']
        self.fields_to_round = {'length_sm': 2, 'length_nm': 2}
        self.table_name = arcpy.ValidateTableName(str(datetime.datetime.now())[0:19])
        self.table_path = os.path.join(arcpy.env.scratchGDB, 
                                       'ShorelineMileages_{}'.format(self.table_name))

        self.fields = ['shp_name', 'shp_path', 'shp_sr', 'calc_sr', 
                       'ccoast_class', 'length_sm', 'length_nm']

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

        arcpy.AddMessage('----- C-COAST CLASS LENGTHS -----')
        class_grouped_df = self.results_df.groupby(self.groupby_fields)
        arcpy.AddMessage(class_grouped_df.sum().round(self.fields_to_round))
        arcpy.AddMessage('---------------------------------')

        arcpy.AddMessage('--------- TOTAL LENGTHS ---------')
        shp_grouped_df = self.results_df.groupby(['shp_name'])
        arcpy.AddMessage(shp_grouped_df.sum().round(self.fields_to_round))
        arcpy.AddMessage('---------------------------------')

    def export_to_table(self):
        """This method exports the overall results table (a Pandas DataFrame)
        to an ArcGIS table in the scratch geodatabase location (as specified
        in the arcpy.env.scratchGDB environment setting)
        """
        arcpy.AddMessage('exporting results to {}...'.format(self.table_path))
        agg_logic = {'shp_sr': 'first', 'shp_path': 'first', 
                     'calc_sr': 'first', 'length_sm': 'sum', 
                     'length_nm': 'sum'}

        df = self.results_df.groupby(self.groupby_fields, as_index=False).agg(agg_logic)
        df = df[self.fields]
        df = df.round(self.fields_to_round)

        x = np.array(np.rec.fromrecords(df.values))
        names = df.dtypes.index.tolist()
        x.dtype.names = tuple(names)
        arcpy.da.NumPyArrayToTable(x, self.table_path)

    def add_table_to_current_map(self):
        """This methods adds the (optional) ArcGIS table to the CURRENT map.
        """
        arcpy.AddMessage('adding {} to CURRENT map...'.format(self.table_path))
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        table_view = arcpy.mapping.TableView(self.table_path)
        arcpy.mapping.AddTableView(df, table_view)
        arcpy.RefreshTOC()
        del mxd


def main():

    # get the user-specified tool settings
    shps = arcpy.GetParameterAsText(0).split(';')   # shapefile(s)
    make_table = arcpy.GetParameterAsText(1)        # create table? (boolean)

    results = ResultsTable()

    # loop through each user-specified shapefile
    for shp_path in shps:

        shp = ShorelineFile(shp_path)
        shp.calc_lengths()
        results.add_shp_results(shp.results)
    
    # display summary table to tool output window
    results.display_summary_table()

    if make_table:
        results.export_to_table()
        results.add_table_to_current_map()


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