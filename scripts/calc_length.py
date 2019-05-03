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


def main():

    # get the user-specified shapefile path(s)
    shps = arcpy.GetParameterAsText(0).split(';')

    # create dict to store results
    results = {'shp_name': [],
               'shp_path': [],
               'original_shp_coord_sys': [],
               'length_sm': [],
               'length_nm': [],
               'calculation_coord_sys': [],      
               }

    # loop through each user-specified shapefile
    for shp_path in shps:

        shp_name = shp_path.split('\\')[-1]

        # get shapefile information
        shp_info = arcpy.Describe(shp_path)
        shp_extent = shp_info.extent
        shp_sr = shp_info.spatialReference

        # determine shapefile's UTM zone
        if shp_sr.type == 'Geographic':
            lon = shp_extent.XMin + (shp_extent.XMax - shp_extent.XMin) / 2
        elif shp_sr.type == 'Projected':
            lon = shp_sr.centralMeridianInDegrees

        utm_zone = int(lon + 180.0) / 6 + 1

        # select EPSG code of relevant projected coordinate system
        utm_zone_epsg = int(epsg_codes[utm_zone][0])

        # define spatial reference to use in searchcursor
        # (because calculations should be done in cartesian space, not unprojected degrees)
        sr = arcpy.SpatialReference(utm_zone_epsg)

        # initialize cumulative length to zero
        cum_length_m = 0

        # loop through polylines, via cursor, adding to cumulative length
        fields = ['SHAPE@', 'SHAPE@LENGTH']
        with arcpy.da.SearchCursor(shp_path, fields, spatial_reference=sr) as cursor:
            for row in cursor:
                cum_length_m += row[1]

        # convert total length to desired units
        length_sm = cum_length_m / METERS_PER_US_STATUTE_MILE
        length_nm = cum_length_m / METERS_PER_US_NAUTICAL_MILE

        # append results to appropriate list in results dict
        results['shp_name'].append(shp_name)
        results['shp_path'].append(shp_path)
        results['original_shp_coord_sys'].append(shp_sr.name)
        results['calculation_coord_sys'].append(epsg_codes[utm_zone][1])
        results['length_sm'].append(round(length_sm, 2))
        results['length_nm'].append(round(length_nm, 2))

    # output total length to user (as pandas dataframe)
    results_df = pd.DataFrame(results, index=results['shp_name']).drop(['shp_name'], axis=1)

    # reorder the columns
    results_df = results_df[['shp_path', 'original_shp_coord_sys', 'calculation_coord_sys', 'length_sm', 'length_nm']]

    # generate geodatabase table from results pandas dataframe
    x = np.array(np.rec.fromrecords(results_df.values))
    names = results_df.dtypes.index.tolist()
    x.dtype.names = tuple(names)
    table_name = str(datetime.datetime.now())[0:19]  # don't need fraction of secs!
    table_name = arcpy.ValidateTableName(table_name)
    table_path = os.path.join(arcpy.env.scratchGDB, 'ShorelineMileages_{}'.format(table_name))
    arcpy.da.NumPyArrayToTable(x, table_path)

    # add geodatabase to the 'CURRENT' map
    mxd = arcpy.mapping.MapDocument("CURRENT")
    df = arcpy.mapping.ListDataFrames(mxd)[0]
    table_view = arcpy.mapping.TableView(table_path)
    arcpy.mapping.AddTableView(df, table_view)
    arcpy.RefreshTOC()
    del mxd


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