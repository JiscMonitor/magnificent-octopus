import json, urllib2
from esprit.models import Query

from flask import Blueprint, request, abort, make_response
from flask.ext.login import current_user

from portality.core import app
from portality.lib import webapp, plugin

blueprint = Blueprint('query', __name__)

# pass queries direct to index. POST only for receipt of complex query objects
@blueprint.route('/<path:path>', methods=['GET','POST'])
@webapp.jsonp
def query(path=None):
    # get the bits out of the path, and ensure that we have at least some parts to work with
    pathparts = path.strip('/').split('/')
    if len(pathparts) == 0:
        abort(400)

    # load the query route config and the path we are being requested for
    qrs = app.config.get("QUERY_ROUTE", {})
    frag = request.path

    # get the configuration for this url route
    route_cfg = None
    for key in qrs:
        if frag.startswith("/" + key):
            route_cfg = qrs.get(key)
            break

    # if no route cfg is found this is not authorised
    if route_cfg is None:
        abort(401)

    # get the configuration for the specific index being queried
    index = pathparts[0]
    cfg = route_cfg.get(index)
    if cfg is None:
        abort(401)

    # does the user have to be authenticated
    if cfg.get("auth"):
        if current_user is None or current_user.is_anonymous():
            abort(401)

        # if so, does the user require a role
        role = cfg.get("roles")
        if role is not None and not current_user.has_role(role):
            abort(401)

    # get the name of the model that will handle this query, and then look up
    # the class that will handle it
    dao_name = cfg.get("dao")
    dao_klass = plugin.load_class(dao_name)
    if dao_klass is None:
        abort(404)

    # now work out what kind of operation is being asked for
    # if _search is specified, then this is a normal query
    search = False
    by_id = None
    if len(pathparts) == 1 or (len(pathparts) == 2 and pathparts[1] == "_search"):
        search = True
    elif len(pathparts) == 2:
        if request.method == "POST":
            abort(401)
        by_id = pathparts[1]
    else:
        abort(400)

    resp = None
    if by_id is not None:
        rec = dao_klass.pull(by_id, wrap=False)
        resp = make_response(rec)
    elif search:
        q = Query()

        # if this is a POST, read the contents out of the body
        if request.method == "POST":
            q = Query(request.json) if request.json else Query(dict(request.form).keys()[-1]) # FIXME: does this actually work?

        # if there is a q param, make it into a query string query
        elif 'q' in request.values:
            s = request.values['q']
            op = request.values.get('default_operator')
            q.query_string(s, op)

        # if there is a source param, load the json from it
        elif 'source' in request.values:
            q = Query(json.loads(urllib2.unquote(request.values['source'])))

        # now run the query through the filters
        filters = app.config.get("QUERY_FILTERS", {})
        filter_names = cfg.get("filters", [])
        for fn in filter_names:
            f = filters.get(fn)
            if f is None:
                abort(500)
            f(q)

        # finally send the query and return the response
        res = dao_klass.query(q=q.as_dict())
        resp = make_response(json.dumps(res))
    else:
        abort(400)

    resp.mimetype = "application/json"
    return resp
