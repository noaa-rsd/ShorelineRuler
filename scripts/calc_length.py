"""
This script is designed to be run via the CalculateShorelineLength tool
in NOAA RSD's in-house ArcGIS toolbox RSD_Toolbox.tbx.

Purpose:
To calculate the total length of polyline features contained in a
user-specified shoreline shapefile

General Steps:
-get the user-specified shapefile path
-determine shapefile's UTM zone, based on longitude midpoint
-select EPSG code of calculated UTM zone
-define spatial reference to use in searchcursor
-loop through polylines, via searchcursor, adding to cumulative length
-convert total length to desired units
-output total length to user

Author:
Nick Forfinski-Sarkozi
nick.forfinski-sarkozi@noaa.gov
"""


import os
import arcpy
import pandas as pd
import numpy as np
import datetime


# create dict to store results
# select EPSG code of relevant projected coordinate system
# define spatial reference to use in searchcursor
# (because calculations should be done in cartesian space, not unprojected degrees)
# initialize cumulative length to zero
# loop through polylines, via cursor, adding to cumulative length
# output total length to user (as pandas dataframe)            
# reorder the columns
# generate geodatabase table from results pandas dataframe
# add geodatabase to the 'CURRENT' map
# append results to appropriate list in results dict


class ShorelineFile:

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
        if self.info.spatialReference.type == 'Geographic':
            x_min = self.info.Extent.XMin
            x_max = self.info.Extent.XMax
            lon = x_min + (x_max - x_min) / 2
        elif self.info.spatialReference.type == 'Projected':
            lon = self.info.spatialReference.centralMeridianInDegrees
        utm_zone = int(lon + 180.0) / 6 + 1
        return utm_zone

    def calc_lengths(self):
        if self.has_ccoast:
            cursor_fields = ['SHAPE@LENGTH', 'CLASS', 'SHAPE@', 'OID@']
        else:
            cursor_fields = ['SHAPE@LENGTH', 'OID@']

        with arcpy.da.SearchCursor(self.shp_path, cursor_fields, 
                                   spatial_reference=self.sr_to_use) as cursor:
            
            for row in cursor:
                if self.has_ccoast:
                    ccoast_class = row[1]
                else:
                    ccoast_class = 'none'

                if type(row[0]) is float:  # make sure length is a number (sometimes geometry is corrupt)
                    self.add_to_shp_results(ccoast_class, row[0])
                else:
                    arcpy.AddWarning('unknown geometry error OID# {} ({}), moving on...'.format(row[-1], self.shp_name))

    def add_to_shp_results(self, ccoast_class, length_m):
        length_sm = length_m / METERS_PER_US_STATUTE_MILE
        length_nm = length_m / METERS_PER_US_NAUTICAL_MILE

        result_info = (self.shp_name, self.shp_path, 
                       self.info.spatialReference.name, self.sr_to_use.name,
                       ccoast_class, length_sm, length_nm, )

        self.results.append(result_info)
        

class ResultsTable:

    def __init__(self):
        self.results = []
        self.table_name = arcpy.ValidateTableName(str(datetime.datetime.now())[0:19])
        self.table_path = os.path.join(arcpy.env.scratchGDB, 
                                       'ShorelineMileages_{}'.format(self.table_name))

        self.fields = ['shp_name', 'shp_path', 'shp_sr', 'calc_sr', 
                       'ccoast_class', 'length_sm', 'length_nm']

    def add_shp_results(self, shp_results):
        self.results.extend(shp_results)

    def export_to_table(self):
        results_df = pd.DataFrame(self.results, columns=self.fields)

        groupby_fields = ['shp_name', 'ccoast_class']
        fields_to_round = {'length_sm': 2, 'length_nm': 2}

        arcpy.AddMessage(results_df.groupby(groupby_fields).sum().round(fields_to_round))

        agg_logic = {'shp_sr': 'first', 'shp_path': 'first', 'calc_sr': 'first', 
                     'length_sm': 'sum', 'length_nm': 'sum'}

        results_df = results_df.groupby(groupby_fields, as_index=False).agg(agg_logic)
        results_df = results_df[self.fields]
        results_df = results_df.round(fields_to_round)

        x = np.array(np.rec.fromrecords(results_df.values))
        names = results_df.dtypes.index.tolist()
        x.dtype.names = tuple(names)
        arcpy.da.NumPyArrayToTable(x, self.table_path)

    def add_table_to_current_map(self):
        mxd = arcpy.mapping.MapDocument("CURRENT")
        df = arcpy.mapping.ListDataFrames(mxd)[0]
        table_view = arcpy.mapping.TableView(self.table_path)
        arcpy.mapping.AddTableView(df, table_view)
        arcpy.RefreshTOC()
        del mxd


def main():

    # get the user-specified shapefile path(s)
    shps = arcpy.GetParameterAsText(0).split(';')

    results = ResultsTable()

    # loop through each user-specified shapefile
    for shp_path in shps:

        shp = ShorelineFile(shp_path)
        shp.calc_lengths()

        results.add_shp_results(shp.results)

    results.export_to_table()
    results.add_table_to_current_map()


if __name__ == "__main__":

    METERS_PER_US_STATUTE_MILE = 1609.3472186944
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