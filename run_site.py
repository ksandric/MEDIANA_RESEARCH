import os
from bottle import route, run, template, request, static_file, error, HTTPResponse
from paste import httpserver

dirname = '.'  # os.path.dirname(sys.argv[0])


@route('/static/<filename:re:.*\.css>')
def send_css(filename):
    return static_file(filename, root=dirname+'/static/css')


@route('/static/<filename:re:.*\.js>')
def send_js(filename):
	return static_file(filename, root=dirname+'/static/js')


@route('/static/images/<filename:re:.*\.png>')
def send_png(filename):
	return static_file(filename, root=dirname+'/static/images')


@route('/static/images/<filename:re:.*\.jpg>')
def send_jpg(filename):
	return static_file(filename, root=dirname+'/static/images')


@route('/static/images/<filename:re:.*\.gif>')
def send_gif(filename):
	return static_file(filename, root=dirname+'/static/images')


@route('/static/images/<filename:re:.*\.ico>')
def send_ico(filename):
	return static_file(filename, root=dirname+'/static/images')


@route('/static/images/<filename:re:.*\.svg>')
def send_ico(filename):
	return static_file(filename, root=dirname+'/static/images')


@route('/<filename:re:.*\.pdf>')
def send_pdf(filename):
	return static_file(filename, root=dirname+'/static')


@route('/<filename:re:.*\.csv>')
def send_pdf(filename):
	return static_file(filename, root=dirname+'/static')


@route('/')
def page_index():
    return template('static/html/page')


@route('/article/<year>/<month>', method='GET')
def page_article(year, month):
    return template(f'static/html/{month}{year}')


@route('/pr/<year>/<month>/<day>')
def page_index(year, month, day):
    return template(f'static/html/pr{day}{month}{year}')


run(server='paste', host='0.0.0.0', port=8080, reloader=False)
