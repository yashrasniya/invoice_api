from rest_framework.pagination import PageNumberPagination


class AdminPagination(PageNumberPagination):
    """Page-number pagination for Product Owner list views.

    Response: {count, next, previous, results}. `?page=` and `?page_size=`
    (max 200).
    """
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 200
