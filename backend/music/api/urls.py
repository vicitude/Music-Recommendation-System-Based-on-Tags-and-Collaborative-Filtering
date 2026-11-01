from django.urls import path

from music.api import views


urlpatterns = [
    path("behaviors/", views.endpoint({"POST": views.recordBehavior}, body_methods=("POST",))),
    path("recommendations/daily/", views.endpoint({"GET": views.getDaily})),
    path("recommendations/daily/refresh/", views.endpoint({"POST": views.refreshDaily})),
    path("auth/csrf/", views.endpoint({"GET": views.getCsrf}, public=True)),
    path("auth/register/", views.endpoint({"POST": views.register}, public=True, body_methods=("POST",))),
    path("auth/login/", views.endpoint({"POST": views.login}, public=True, body_methods=("POST",))),
    path("auth/logout/", views.endpoint({"POST": views.logout})),
    path("me/", views.endpoint({"GET": views.getMe})),
    path("me/interests/", views.endpoint({"GET": views.getInterests, "PUT": views.setInterests}, body_methods=("PUT",))),
    path("tags/", views.endpoint({"GET": views.listTags}, public=True)),
    path("songs/", views.endpoint({"GET": views.listSongs}, public=True)),
    path("songs/<int:id>/", views.endpoint({"GET": views.getSong}, public=True)),
    path("songs/<int:id>/stream/", views.endpoint({"GET": views.streamSong})),
    path("favorites/", views.endpoint({"GET": views.listFavorites})),
    path("favorites/<int:id>/", views.endpoint({"PUT": views.addFavorite, "DELETE": views.removeFavorite})),
    path("playlists/", views.endpoint({"GET": views.listPlaylists, "POST": views.createPlaylist}, body_methods=("POST",))),
    path("playlists/<int:id>/", views.endpoint(
        {"GET": views.getPlaylist, "PATCH": views.renamePlaylist, "DELETE": views.deletePlaylist},
        body_methods=("PATCH",),
    )),
    path("playlists/<int:id>/songs/<int:song_id>/", views.endpoint(
        {"PUT": views.addPlaylistSong, "DELETE": views.removePlaylistSong},
    )),
]
