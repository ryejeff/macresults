#!/usr/bin/env python3
#
# pylint: disable=missing-docstring
#
# This script reads a series of event results files, computes the DOTY
# points, and creates an HTML file with the results neatly formatted.
#
# Invoke this as:
# pylint: disable=line-too-long
#
# ./publish_series.py -t 'MOWOG 2018' -n 9 -b 5 -o 2018/mowog_series.html gen/mowog1.json gen/mowog2.json gen/mowog3.json
#
# pylint: enable=line-too-long
#

import argparse
import base64
import math
import sys

import numpy as np
import pandas as pd

import pystache


def main(args):
    parser = argparse.ArgumentParser()
    parser.add_argument('results_filenames',
                        nargs='+',
                        help='The results files. Will extract results from ' +
                        'these.')
    parser.add_argument('-o',
                        dest='output_filename',
                        help='The output file. Will write the HTML results ' +
                        'to this file.')
    parser.add_argument('-t',
                        dest='title',
                        default='MAC DOTY Results',
                        help='The title to put in the results file.')
    parser.add_argument('-n',
                        dest='num_events',
                        default=9,
                        type=int,
                        help='The number of events in the season.')
    parser.add_argument('-b',
                        dest='num_btp_events',
                        default=5,
                        type=int,
                        help='The number of events contributing to the ' +
                        'final DOTY score.')
    config = parser.parse_args(args)

    # Read the event results files.
    results = load_results(config)

    return

    # Set up the templating.
    stache = pystache.Renderer(file_extension=False,
                               partials={})
    stache.partials['style'] = stache.load_template('templates/style.css')

    # Prepare the data do go in the template.
    options = {
        'title': config.title,
        'events': ['M%d' % event_num for event_num in range(1, config.num_events + 1)]
    }
    # print(options)
    options['logoDataUri'] = get_image_data_uri('templates/mac-logo-small.png')

    options['results'] = prepare_results_for_template(results, config)
    # FIXME Now that we have the series classes and times for each
    # driver for each event, prepare the classes to render. If a
    # driver ran in multiple classes, they should show up in all of
    # them with the correct points in each.

    # FIXME Then, we need to actually pass these class-based values to
    # the template (and the template should render them in groups,
    # like the publish_results.py script does).

    # Apply the template and write the result.
    doty_results_template = \
      stache.load_template('templates/series-results.html')
    html = stache.render(doty_results_template, options)
    if config.output_filename:
        print('Writing series results to: %s' % config.output_filename)
        with open(config.output_filename, 'wt') as output_file:
            output_file.write(html)
    else:
        print(html)


# ------------------------------------------------------------
# Helper functions

def load_results(config):
    # results = pd.DataFrame(index=['driver', 'series_class'])
    results = None

    event_num = 1
    event_names = []
    for results_filename in config.results_filenames:
        event_name = 'M%d' % event_num
        event_names.append(event_name)

        print('Reading results for %s:' % event_name)
        print('  %s' % results_filename)
        event_results = pd.read_json(results_filename,
                                     orient='records', lines=True)

        # Prepare the driver names.
        event_results['driver'] = \
          event_results['FirstName'] + ' ' + event_results['LastName']

        # Compute series class and series time here.
        event_results = event_results.apply(add_series_values,
                                            axis=1, args=[config])

        # Drop rows with no class. This will prune the Novice and X
        # classes.
        event_results = event_results.dropna(subset=['series_class'])

        # Compute the points for this event.
        event_class_groups = event_results.groupby(by=['series_class'])
        # print(event_class_groups.groups)
        event_results = event_results.apply(add_series_points,
                                            axis=1,
                                            args=[event_class_groups, event_name, config])

        # Merge these results into the main results. We are merging on
        # the shared columns, so be careful what goes into the
        # sub-dataframe.
        results_to_merge = event_results[['driver', 'series_class', event_name]]
        # print(results_to_merge)
        if results is None:
            results = results_to_merge
        else:
            results = results.merge(results_to_merge,
                                    how='outer')

        event_num = event_num + 1

    # FIXME These cannot be done here. They need to be done on a
    # class-by-class basis.
    # results['total_points'] = results[event_names].sum(axis=1)
    # results['avg_points'] = results[event_names].mean(axis=1)
    # results['num_events'] = results[event_names].count(axis=1)

    # results = results.apply(add_btp_scores, axis=1, args=[event_names, config])

    # Done, time to return the fruits of our labors.
    print(results)
    return results


def add_series_values(row, config):
    excluded_classes = set(['N', 'X'])

    # final_time is the combined time for Pro and the indexed time for
    # Z. For all other classes (notably including those in combined
    # classes), we just take the raw time.
    if row['class_index'] == 'P':
        series_class = 'P'
        series_time = row['final_time']
    elif row['class_index'] == 'Z':
        series_class = 'Z'
        series_time = row['final_time']
    elif row['class_name'] in excluded_classes:
        series_class = None
        series_time = None
    else:
        series_class = row['class_name']
        series_time = row['best_raw_time']

    row['series_class'] = series_class
    row['series_time'] = series_time
    return row


def add_series_points(row, event_class_groups, event_name, config):
    series_class = row['series_class']
    series_time = row['series_time']
    if series_class in event_class_groups.groups:
        series_group = event_class_groups.get_group(series_class)
        best_class_time = series_group['series_time'].min()
        series_points = best_class_time / series_time * 100.0
        # print('class? %s  =>  %0.3f / %0.3f = %0.3f' %
        #       (series_class, best_class_time, series_time, series_points))
        row[event_name] = series_points
    return row


def add_btp_scores(row, event_names, config):
    actual_event_count = len(event_names)

    # Assume 100.0 points for each remaining event.
    num_remaining_events = config.num_events - actual_event_count
    if num_remaining_events > config.num_btp_events:
        num_remaining_events = config.num_btp_events
    best_remaining_score = 100.0 * num_remaining_events

    # Get the keeper scores.
    scores = [0.0 if math.isnan(score) else score for score in row[event_names]]
    scores = sorted(scores, reverse=True)

    num_scores_to_keep = config.num_btp_events - num_remaining_events
    kept_scores = scores[:num_scores_to_keep]

    kept_score = sum(kept_scores)

    # Record the result
    row['btp'] = kept_score + best_remaining_score
    return row


def prepare_results_for_template(results_df, config):
    sorted_results = results_df.sort_values(by=['total_points'],
                                            ascending=False)
    results = []
    rank = 0

    first_score = None
    prev_score = None
    for _, row in sorted_results.iterrows():
        result = {}
        rank = rank + 1
        result['rank'] = rank

        result['driver'] = row['driver']

        result['num_events'] = row['num_events']

        final_score = row['total_points']
        result['total_points'] = format_score(final_score)

        if not first_score:
            result['diffFromFirst'] = '-'
            result['diffFromPrev'] = '-'
            first_score = final_score
        else:
            result['diffFromFirst'] = format_score(final_score - first_score)
            result['diffFromPrev'] = format_score(final_score - prev_score)
        prev_score = final_score

        event_scores = []
        for event_num in range(1, config.num_events + 1):
            event_name = 'M%d' % event_num
            event_score = None
            try:
                event_score = row[event_name]
            except KeyError:
                # Didn't have any result for this array, use the
                # default value.
                pass
            event_scores.append(format_score(event_score))
        result['event_scores'] = event_scores

        result['avg_points'] = format_score(row['avg_points'])
        result['btp'] = format_score(row['btp'])

        results.append(result)

    return results


# FIXME This is duplicated with the publish_results.py script, we
# should put them in a common place.
def get_image_data_uri(filename):
    with open(filename, 'rb') as in_file:
        raw_data = in_file.read()
        base64_data = base64.b64encode(raw_data)
        data_uri = 'data:image/png;base64,' + base64_data.decode('utf-8')
        return data_uri


def format_score(score):
    if score is None or math.isnan(score):
        formatted_score = '-'
    else:
        formatted_score = '%0.3f' % score
    return formatted_score


# ------------------------------------------------------------
# This is the magic that runs the main function when this is invoked
# as a script.

if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))