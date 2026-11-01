Feature: SPEC-MUSIC-001 explicit boundaries
  Step bindings are not implemented; these are not test results.

  @TC-M-013
  Scenario: Pausing cannot inflate listening
    Given a 100000 millisecond song and an accepted PLAY
    And server time advances 600000 milliseconds
    When I POST COMPLETE with position_ms 90000 and listened_ms 1000 to "/api/v1/behaviors/"
    Then the status is 409 with error_code "INVALID_TRANSITION"

  @TC-M-014
  Scenario: Empty library pagination
    Given no songs are active
    When I GET "/api/v1/songs/?page=1"
    Then the status is 200 with count 0 and empty results
    When I GET "/api/v1/songs/?page=2"
    Then the status is 404 with error_code "NOT_FOUND"

  @TC-M-015
  Scenario: Hide unpublished songs without deleting membership
    Given I own playlist 10 containing song 1
    When song 1 is unpublished
    Then GET "/api/v1/playlists/10/" omits song 1
    And the stored membership remains

  @TC-M-016
  Scenario: CSRF precedes authentication
    Given I have no session and no CSRF token
    When I POST "/api/v1/recommendations/daily/refresh/"
    Then the status is 403 with error_code "CSRF_FAILED"
    When I retry with valid CSRF but no session
    Then the status is 401 with error_code "AUTH_REQUIRED"
