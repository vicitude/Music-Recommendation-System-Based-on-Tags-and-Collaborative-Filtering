from django.urls import path

from music.api import views


urlpatterns = [
    path("users/<int:id>/", views.endpoint({"GET": views.getUser})),
    path("users/<int:id>/following/", views.endpoint({"GET": views.listFollowing})),
    path("users/<int:id>/followers/", views.endpoint({"GET": views.listFollowers})),
    path("users/<int:id>/follow/", views.endpoint({"PUT": views.followUser, "DELETE": views.unfollowUser})),
    path("behaviors/", views.endpoint({"POST": views.recordBehavior}, body_methods=("POST",))),
    path("recommendations/daily/", views.endpoint({"GET": views.getDaily})),
    path("recommendations/daily/refresh/", views.endpoint({"POST": views.refreshDaily})),
    path("auth/csrf/", views.endpoint({"GET": views.getCsrf}, public=True)),
    path("auth/register/", views.endpoint({"POST": views.register}, public=True, body_methods=("POST",))),
    path("auth/login/", views.endpoint({"POST": views.login}, public=True, body_methods=("POST",))),
    path("auth/logout/", views.endpoint({"POST": views.logout})),
    path("me/", views.endpoint({"GET": views.getMe})),
    path("me/history/", views.endpoint({"GET": views.getHistory})),
    path("me/interests/", views.endpoint({"GET": views.getInterests, "PUT": views.setInterests}, body_methods=("PUT",))),
    path("tags/", views.endpoint({"GET": views.listTags}, public=True)),
    path("songs/", views.endpoint({"GET": views.listSongs}, public=True)),
    path("songs/<int:id>/", views.endpoint({"GET": views.getSong}, public=True)),
    path("songs/<int:id>/comments/", views.endpoint({"GET": views.listComments, "POST": views.createComment}, public=True, body_methods=("POST",))),
    path("comments/<int:id>/", views.endpoint({"DELETE": views.deleteComment})),
    path("songs/<int:id>/stream/", views.endpoint({"GET": views.streamSong})),
    path("songs/<int:id>/rating/", views.endpoint({"GET": views.getRating, "PUT": views.setRating, "DELETE": views.removeRating}, body_methods=("PUT",))),
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
